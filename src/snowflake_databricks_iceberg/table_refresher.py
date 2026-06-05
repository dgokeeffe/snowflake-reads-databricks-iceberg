"""
Refresh Snowflake Iceberg tables with Unity Catalog metadata.

Uses PyIceberg to get latest metadata.json paths from Databricks Unity Catalog,
then creates/refreshes Snowflake Iceberg tables pointing to those paths.
"""

import os
import re
import subprocess
from typing import Optional, List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import snowflake.connector
from dotenv import load_dotenv

from snowflake_databricks_iceberg.catalog_client import IcebergCatalogClient

load_dotenv()


class TableRefresher:
    """
    Refresh Snowflake Iceberg tables with Unity Catalog metadata.

    Uses PyIceberg to get the latest metadata.json path for each table,
    then creates or refreshes the corresponding Snowflake Iceberg table.

    Example:
        >>> refresher = TableRefresher(
        ...     databricks_catalog="main",
        ...     databricks_schema="my_schema",
        ...     snowflake_db="MY_DB",
        ...     snowflake_schema="MY_SCHEMA",
        ...     external_volume="my_volume"
        ... )
        >>> results = refresher.refresh_all()
    """

    def __init__(
        self,
        databricks_catalog: str,
        databricks_schema: str,
        snowflake_db: str,
        snowflake_schema: str,
        external_volume: str,
        workspace_host: Optional[str] = None,
    ):
        """
        Initialize the table refresher.

        Args:
            databricks_catalog: Unity Catalog name
            databricks_schema: Schema containing Iceberg tables
            snowflake_db: Target Snowflake database
            snowflake_schema: Target Snowflake schema
            external_volume: Snowflake external volume name
            workspace_host: Databricks workspace URL (auto-detected if None)
        """
        self.databricks_catalog = databricks_catalog
        self.databricks_schema = databricks_schema
        self.snowflake_db = snowflake_db
        self.snowflake_schema = snowflake_schema
        self.external_volume = external_volume

        # Get workspace host
        self.workspace_host = workspace_host or os.getenv("DATABRICKS_HOST")
        if not self.workspace_host:
            raise ValueError(
                "workspace_host required. Provide it or set DATABRICKS_HOST."
            )

        # Initialize clients
        self._iceberg_client = None
        self._sf_conn = None

    @property
    def iceberg_client(self) -> IcebergCatalogClient:
        """Get PyIceberg catalog client."""
        if self._iceberg_client is None:
            self._iceberg_client = IcebergCatalogClient(
                workspace_host=self.workspace_host,
                catalog_name=self.databricks_catalog,
            )
        return self._iceberg_client

    @property
    def snowflake_conn(self) -> snowflake.connector.SnowflakeConnection:
        """Get Snowflake connection."""
        if self._sf_conn is None:
            self._sf_conn = self._connect_snowflake()
        return self._sf_conn

    def _connect_snowflake(self) -> snowflake.connector.SnowflakeConnection:
        """Create Snowflake connection."""
        required_vars = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
        missing = [v for v in required_vars if not os.getenv(v)]

        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

        conn = snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        )

        # Ensure database and schema exist
        cursor = conn.cursor()
        try:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.snowflake_db}")
            cursor.execute(f"USE DATABASE {self.snowflake_db}")
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.snowflake_schema}")
            cursor.execute(f"USE SCHEMA {self.snowflake_schema}")
        finally:
            cursor.close()

        return conn

    def convert_abfss_to_snowflake_path(self, abfss_url: str) -> str:
        """
        Convert abfss:// URL to Snowflake metadata file path.

        The path should be relative to the external volume's STORAGE_BASE_URL.

        Args:
            abfss_url: Full abfss:// path to metadata.json

        Returns:
            Relative path for Snowflake METADATA_FILE_PATH
        """
        # Parse: abfss://container@account.dfs.core.windows.net/path
        match = re.match(r"abfss://([^@]+)@([^/]+)/(.+)", abfss_url)
        if not match:
            raise ValueError(f"Invalid abfss URL format: {abfss_url}")

        _, _, path = match.groups()

        # Remove leading slash and 'root/' prefix if present
        path = path.lstrip("/")
        if path.startswith("root/"):
            path = path[5:]

        return path.lstrip("/")

    def list_tables(self) -> List[str]:
        """List all tables in the Databricks schema."""
        return self.iceberg_client.list_tables(self.databricks_schema)

    def get_metadata_path(self, table_name: str) -> Optional[str]:
        """
        Get the metadata.json path for a table.

        Uses PyIceberg to get the latest metadata location from Unity Catalog.

        Args:
            table_name: Table name

        Returns:
            Relative path for Snowflake, or None if not found
        """
        try:
            metadata_location = self.iceberg_client.get_metadata_location(
                self.databricks_schema, table_name
            )

            if metadata_location:
                return self.convert_abfss_to_snowflake_path(metadata_location)
        except Exception as e:
            print(f"Could not get metadata for {table_name}: {e}")

        return None

    def _ensure_catalog_integration(self, cursor) -> str:
        """Ensure catalog integration exists for external volume."""
        integration_name = f"{self.external_volume}_catalog"

        try:
            cursor.execute("SHOW CATALOG INTEGRATIONS")
            integrations = cursor.fetchall()
            names = [str(row[0]).strip().upper() for row in integrations]

            if integration_name.upper() not in names:
                cursor.execute(f"""
                    CREATE CATALOG INTEGRATION {integration_name}
                      CATALOG_SOURCE = OBJECT_STORE
                      TABLE_FORMAT = ICEBERG
                      ENABLED = TRUE;
                """)
                print(f"Created catalog integration: {integration_name}")

        except Exception as e:
            if "already exists" not in str(e).lower():
                raise

        return integration_name

    def refresh_table(
        self,
        table_name: str,
        metadata_path: str,
    ) -> Tuple[str, bool, Optional[str]]:
        """
        Create or refresh a single Snowflake Iceberg table.

        Args:
            table_name: Table name
            metadata_path: Relative path to metadata.json

        Returns:
            Tuple of (table_name, success, error_message)
        """
        cursor = self.snowflake_conn.cursor()

        try:
            cursor.execute(f"USE DATABASE {self.snowflake_db}")
            cursor.execute(f"USE SCHEMA {self.snowflake_schema}")

            catalog_integration = self._ensure_catalog_integration(cursor)

            # Check if table exists
            cursor.execute(f"SHOW ICEBERG TABLES LIKE '{table_name.upper()}'")
            table_exists = len(cursor.fetchall()) > 0

            if not table_exists:
                # Create new table
                create_sql = f"""
                    CREATE ICEBERG TABLE IF NOT EXISTS {table_name}
                      CATALOG = '{catalog_integration}'
                      EXTERNAL_VOLUME = '{self.external_volume}'
                      METADATA_FILE_PATH = '{metadata_path}';
                """
                cursor.execute(create_sql)
                return (table_name, True, None)
            else:
                # Refresh existing table
                refresh_sql = f"ALTER ICEBERG TABLE {table_name} REFRESH '{metadata_path}';"
                try:
                    cursor.execute(refresh_sql)
                    return (table_name, True, None)
                except Exception as refresh_error:
                    error_msg = str(refresh_error).lower()

                    # UUID mismatch - recreate table
                    if "uuid" in error_msg and "does not match" in error_msg:
                        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                        create_sql = f"""
                            CREATE ICEBERG TABLE {table_name}
                              CATALOG = '{catalog_integration}'
                              EXTERNAL_VOLUME = '{self.external_volume}'
                              METADATA_FILE_PATH = '{metadata_path}';
                        """
                        cursor.execute(create_sql)
                        return (table_name, True, None)
                    else:
                        raise

        except Exception as e:
            return (table_name, False, str(e))

        finally:
            cursor.close()

    def refresh_all(self, parallel: int = 2) -> Dict[str, bool]:
        """
        Refresh all tables in the schema.

        Args:
            parallel: Number of parallel workers

        Returns:
            Dictionary mapping table names to success status
        """
        print(f"\nDiscovering tables in {self.databricks_catalog}.{self.databricks_schema}...")
        tables = self.list_tables()

        if not tables:
            print("No tables found")
            return {}

        print(f"Found {len(tables)} tables")

        # Get metadata paths
        print("\nGetting metadata paths from Unity Catalog...")
        table_metadata = {}

        for table in tables:
            path = self.get_metadata_path(table)
            if path:
                table_metadata[table] = path
                print(f"  {table}: {path}")
            else:
                print(f"  {table}: No metadata found")

        if not table_metadata:
            print("\nNo metadata paths found")
            return {}

        # Refresh tables
        print(f"\nRefreshing {len(table_metadata)} tables in Snowflake...")
        results = {}

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {
                executor.submit(self.refresh_table, name, path): name
                for name, path in table_metadata.items()
            }

            for future in as_completed(futures):
                table_name, success, error = future.result()
                results[table_name] = success

                if success:
                    print(f"  ✓ {table_name}")
                else:
                    print(f"  ✗ {table_name}: {error}")

        # Summary
        successful = sum(1 for v in results.values() if v)
        failed = len(results) - successful

        print(f"\nResults: {successful} succeeded, {failed} failed")

        return results

    def close(self):
        """Close connections."""
        if self._sf_conn:
            self._sf_conn.close()
            self._sf_conn = None


def main():
    """CLI entry point for table refresh."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Refresh Snowflake Iceberg tables from Unity Catalog"
    )
    parser.add_argument(
        "--catalog",
        required=True,
        help="Databricks Unity Catalog name",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Databricks schema name",
    )
    parser.add_argument(
        "--snowflake-db",
        required=True,
        help="Snowflake database name",
    )
    parser.add_argument(
        "--snowflake-schema",
        required=True,
        help="Snowflake schema name",
    )
    parser.add_argument(
        "--external-volume",
        required=True,
        help="Snowflake external volume name",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=2,
        help="Number of parallel workers (default: 2)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Refresh Snowflake Iceberg Tables")
    print("=" * 60)
    print(f"Source: {args.catalog}.{args.schema}")
    print(f"Target: {args.snowflake_db}.{args.snowflake_schema}")
    print(f"Volume: {args.external_volume}")
    print("=" * 60)

    refresher = TableRefresher(
        databricks_catalog=args.catalog,
        databricks_schema=args.schema,
        snowflake_db=args.snowflake_db,
        snowflake_schema=args.snowflake_schema,
        external_volume=args.external_volume,
    )

    try:
        results = refresher.refresh_all(parallel=args.parallel)

        if not results:
            exit(1)

        failed = sum(1 for v in results.values() if not v)
        if failed > 0:
            exit(1)

    finally:
        refresher.close()


if __name__ == "__main__":
    main()
