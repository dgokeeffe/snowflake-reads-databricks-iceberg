"""
Snowflake Catalog Integration for Iceberg Tables.

Snowflake requires a CATALOG INTEGRATION to read Iceberg tables. There are two types:

1. ICEBERG_REST - For REST API access to external catalogs (e.g., Unity Catalog)
2. OBJECT_STORE - For direct storage access via External Volume + metadata.json path

This module provides utilities for creating and managing both types.

Reference:
    https://docs.snowflake.com/en/sql-reference/sql/create-catalog-integration
"""

import os
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import snowflake.connector
from dotenv import load_dotenv

load_dotenv()


class CatalogSource(Enum):
    """Snowflake Catalog Integration source types."""

    # REST API catalog (Unity Catalog, Polaris, etc.)
    ICEBERG_REST = "ICEBERG_REST"

    # Object store with metadata.json path
    OBJECT_STORE = "OBJECT_STORE"


@dataclass
class CatalogIntegrationConfig:
    """Configuration for a catalog integration."""

    name: str
    catalog_source: CatalogSource
    enabled: bool = True

    # For ICEBERG_REST
    catalog_uri: Optional[str] = None
    catalog_namespace: Optional[str] = None
    warehouse: Optional[str] = None  # Databricks catalog name
    oauth_token_uri: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None

    # For OBJECT_STORE
    # No additional config needed - just the integration name


class CatalogIntegration:
    """
    Manage Snowflake Catalog Integrations for Iceberg tables.

    Snowflake REQUIRES a Catalog Integration to read Iceberg tables.
    This is true for BOTH methods:

    1. REST Integration (AUTO_REFRESH capable):
       - CATALOG_SOURCE = ICEBERG_REST
       - Uses OAuth to connect to Unity Catalog REST API
       - Supports vended credentials and auto-refresh

    2. External Volume (Manual refresh):
       - CATALOG_SOURCE = OBJECT_STORE
       - Reads directly from storage via metadata.json path
       - Requires manual refresh when data changes

    Example (Object Store):
        >>> integration = CatalogIntegration()
        >>> integration.create_object_store("my_volume_catalog")

    Example (REST):
        >>> integration = CatalogIntegration()
        >>> integration.create_rest(
        ...     name="databricks_rest",
        ...     workspace_host="https://adb-xxx.azuredatabricks.net",
        ...     catalog_name="main",
        ...     schema_name="my_schema",
        ...     client_id="xxx",
        ...     client_secret="xxx"
        ... )
    """

    def __init__(self, connection: Optional[snowflake.connector.SnowflakeConnection] = None):
        """
        Initialize catalog integration manager.

        Args:
            connection: Existing Snowflake connection, or None to create new
        """
        self._conn = connection

    @property
    def connection(self) -> snowflake.connector.SnowflakeConnection:
        """Get or create Snowflake connection."""
        if self._conn is None:
            self._conn = self._create_connection()
        return self._conn

    def _create_connection(self) -> snowflake.connector.SnowflakeConnection:
        """Create Snowflake connection from environment."""
        required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"]
        missing = [v for v in required if not os.getenv(v)]

        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

        return snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        )

    def exists(self, name: str) -> bool:
        """Check if a catalog integration exists."""
        cursor = self.connection.cursor()
        try:
            cursor.execute("SHOW CATALOG INTEGRATIONS")
            integrations = cursor.fetchall()
            names = [str(row[0]).strip().upper() for row in integrations]
            return name.upper() in names
        finally:
            cursor.close()

    def create_object_store(
        self,
        name: str,
        replace: bool = False,
    ) -> str:
        """
        Create OBJECT_STORE catalog integration for External Volume tables.

        This is REQUIRED for Iceberg tables that use:
        - EXTERNAL_VOLUME
        - METADATA_FILE_PATH

        Args:
            name: Integration name (typically: {external_volume}_catalog)
            replace: If True, replace existing integration

        Returns:
            Integration name

        SQL Generated:
            CREATE CATALOG INTEGRATION {name}
              CATALOG_SOURCE = OBJECT_STORE
              TABLE_FORMAT = ICEBERG
              ENABLED = TRUE;
        """
        cursor = self.connection.cursor()
        try:
            if self.exists(name) and not replace:
                print(f"Catalog integration '{name}' already exists")
                return name

            create_or_replace = "CREATE OR REPLACE" if replace else "CREATE"

            sql = f"""
                {create_or_replace} CATALOG INTEGRATION {name}
                  CATALOG_SOURCE = OBJECT_STORE
                  TABLE_FORMAT = ICEBERG
                  ENABLED = TRUE;
            """

            cursor.execute(sql)
            print(f"Created catalog integration: {name}")
            print(f"  CATALOG_SOURCE = OBJECT_STORE")
            print(f"  TABLE_FORMAT = ICEBERG")

            return name

        finally:
            cursor.close()

    def create_rest(
        self,
        name: str,
        workspace_host: str,
        catalog_name: str,
        schema_name: str,
        client_id: str,
        client_secret: str,
        replace: bool = False,
    ) -> str:
        """
        Create ICEBERG_REST catalog integration for Unity Catalog.

        This enables:
        - AUTO_REFRESH for automatic metadata sync
        - Vended credentials (temporary SAS tokens)
        - OAuth authentication

        Args:
            name: Integration name
            workspace_host: Databricks workspace URL
            catalog_name: Unity Catalog name (goes in WAREHOUSE)
            schema_name: Schema name (goes in CATALOG_NAMESPACE)
            client_id: OAuth client ID
            client_secret: OAuth client secret
            replace: If True, replace existing integration

        Returns:
            Integration name

        SQL Generated:
            CREATE CATALOG INTEGRATION {name}
              CATALOG_SOURCE = ICEBERG_REST
              TABLE_FORMAT = ICEBERG
              CATALOG_NAMESPACE = '{schema_name}'
              REST_CONFIG = (
                CATALOG_URI = '{workspace_host}/api/2.1/unity-catalog/iceberg'
                WAREHOUSE = '{catalog_name}'
                ACCESS_DELEGATION_MODE = 'VENDED_CREDENTIALS'
              )
              REST_AUTHENTICATION = (
                TYPE = OAUTH
                OAUTH_TOKEN_URI = '{workspace_host}/oidc/v1/token'
                OAUTH_CLIENT_ID = '{client_id}'
                OAUTH_CLIENT_SECRET = '{client_secret}'
                OAUTH_ALLOWED_SCOPES = ('all-apis')
              );
        """
        cursor = self.connection.cursor()
        try:
            if self.exists(name) and not replace:
                print(f"Catalog integration '{name}' already exists")
                return name

            workspace_host = workspace_host.rstrip("/")
            create_or_replace = "CREATE OR REPLACE" if replace else "CREATE"

            sql = f"""
                {create_or_replace} CATALOG INTEGRATION {name}
                  CATALOG_SOURCE = ICEBERG_REST
                  TABLE_FORMAT = ICEBERG
                  CATALOG_NAMESPACE = '{schema_name}'
                  REST_CONFIG = (
                    CATALOG_URI = '{workspace_host}/api/2.1/unity-catalog/iceberg'
                    WAREHOUSE = '{catalog_name}'
                    ACCESS_DELEGATION_MODE = 'VENDED_CREDENTIALS'
                  )
                  REST_AUTHENTICATION = (
                    TYPE = OAUTH
                    OAUTH_TOKEN_URI = '{workspace_host}/oidc/v1/token'
                    OAUTH_CLIENT_ID = '{client_id}'
                    OAUTH_CLIENT_SECRET = '{client_secret}'
                    OAUTH_ALLOWED_SCOPES = ('all-apis')
                  );
            """

            cursor.execute(sql)
            print(f"Created catalog integration: {name}")
            print(f"  CATALOG_SOURCE = ICEBERG_REST")
            print(f"  CATALOG_URI = {workspace_host}/api/2.1/unity-catalog/iceberg")
            print(f"  WAREHOUSE = {catalog_name}")
            print(f"  CATALOG_NAMESPACE = {schema_name}")

            return name

        finally:
            cursor.close()

    def describe(self, name: str) -> dict:
        """Describe a catalog integration."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(f"DESC CATALOG INTEGRATION {name}")
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            cursor.close()

    def drop(self, name: str) -> bool:
        """Drop a catalog integration."""
        cursor = self.connection.cursor()
        try:
            cursor.execute(f"DROP CATALOG INTEGRATION IF EXISTS {name}")
            print(f"Dropped catalog integration: {name}")
            return True
        except Exception as e:
            print(f"Failed to drop {name}: {e}")
            return False
        finally:
            cursor.close()

    @staticmethod
    def generate_object_store_sql(name: str) -> str:
        """Generate SQL for OBJECT_STORE catalog integration."""
        return f"""-- Catalog Integration for External Volume Iceberg Tables
-- This is REQUIRED for tables using EXTERNAL_VOLUME + METADATA_FILE_PATH

CREATE CATALOG INTEGRATION {name}
  CATALOG_SOURCE = OBJECT_STORE
  TABLE_FORMAT = ICEBERG
  ENABLED = TRUE;

-- Verify
DESC CATALOG INTEGRATION {name};
"""

    @staticmethod
    def generate_rest_sql(
        name: str,
        workspace_host: str,
        catalog_name: str,
        schema_name: str,
        client_id: str = "<client_id>",
        client_secret: str = "<client_secret>",
    ) -> str:
        """Generate SQL for ICEBERG_REST catalog integration."""
        workspace_host = workspace_host.rstrip("/")

        return f"""-- REST Catalog Integration for Unity Catalog
-- Enables AUTO_REFRESH and vended credentials

CREATE CATALOG INTEGRATION {name}
  CATALOG_SOURCE = ICEBERG_REST
  TABLE_FORMAT = ICEBERG
  CATALOG_NAMESPACE = '{schema_name}'
  REST_CONFIG = (
    CATALOG_URI = '{workspace_host}/api/2.1/unity-catalog/iceberg'
    WAREHOUSE = '{catalog_name}'
    ACCESS_DELEGATION_MODE = 'VENDED_CREDENTIALS'
  )
  REST_AUTHENTICATION = (
    TYPE = OAUTH
    OAUTH_TOKEN_URI = '{workspace_host}/oidc/v1/token'
    OAUTH_CLIENT_ID = '{client_id}'
    OAUTH_CLIENT_SECRET = '{client_secret}'
    OAUTH_ALLOWED_SCOPES = ('all-apis')
  );

-- Verify
DESC CATALOG INTEGRATION {name};
"""


def main():
    """CLI entry point for catalog integration management."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage Snowflake Catalog Integrations for Iceberg"
    )

    subparsers = parser.add_subparsers(dest="command")

    # Create OBJECT_STORE
    obj_parser = subparsers.add_parser(
        "create-object-store",
        help="Create OBJECT_STORE catalog integration",
    )
    obj_parser.add_argument("--name", required=True, help="Integration name")
    obj_parser.add_argument("--replace", action="store_true", help="Replace if exists")

    # Create REST
    rest_parser = subparsers.add_parser(
        "create-rest",
        help="Create ICEBERG_REST catalog integration",
    )
    rest_parser.add_argument("--name", required=True, help="Integration name")
    rest_parser.add_argument("--workspace-host", required=True, help="Databricks URL")
    rest_parser.add_argument("--catalog", required=True, help="Unity Catalog name")
    rest_parser.add_argument("--schema", required=True, help="Schema name")
    rest_parser.add_argument("--client-id", required=True, help="OAuth client ID")
    rest_parser.add_argument("--client-secret", required=True, help="OAuth secret")
    rest_parser.add_argument("--replace", action="store_true", help="Replace if exists")

    # Generate SQL
    sql_parser = subparsers.add_parser("generate-sql", help="Generate SQL only")
    sql_parser.add_argument(
        "--type",
        choices=["object-store", "rest"],
        required=True,
    )
    sql_parser.add_argument("--name", required=True)
    sql_parser.add_argument("--workspace-host", help="For REST type")
    sql_parser.add_argument("--catalog", help="For REST type")
    sql_parser.add_argument("--schema", help="For REST type")

    # List
    subparsers.add_parser("list", help="List catalog integrations")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    integration = CatalogIntegration()

    if args.command == "create-object-store":
        integration.create_object_store(args.name, args.replace)

    elif args.command == "create-rest":
        integration.create_rest(
            name=args.name,
            workspace_host=args.workspace_host,
            catalog_name=args.catalog,
            schema_name=args.schema,
            client_id=args.client_id,
            client_secret=args.client_secret,
            replace=args.replace,
        )

    elif args.command == "generate-sql":
        if args.type == "object-store":
            print(CatalogIntegration.generate_object_store_sql(args.name))
        else:
            if not all([args.workspace_host, args.catalog, args.schema]):
                print("REST type requires --workspace-host, --catalog, --schema")
                return
            print(
                CatalogIntegration.generate_rest_sql(
                    args.name,
                    args.workspace_host,
                    args.catalog,
                    args.schema,
                )
            )

    elif args.command == "list":
        cursor = integration.connection.cursor()
        cursor.execute("SHOW CATALOG INTEGRATIONS")
        rows = cursor.fetchall()
        print("Catalog Integrations:")
        for row in rows:
            print(f"  - {row[0]}: {row[1]}")
        cursor.close()


if __name__ == "__main__":
    main()
