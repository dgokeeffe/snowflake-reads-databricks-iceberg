"""
PyIceberg client for Databricks Unity Catalog.

Connects to the Databricks Iceberg REST API to access Unity Catalog tables
as Apache Iceberg tables.

Supports multiple authentication methods:
- Databricks PAT token
- Azure CLI (az login)
- Entra ID Service Principal (client credentials)

Reference:
    https://learn.microsoft.com/azure/databricks/external-access/iceberg
"""

import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class TableInfo:
    """Information about an Iceberg table."""

    name: str
    schema: str
    catalog: str
    metadata_location: str
    properties: Dict[str, Any]


class IcebergCatalogClient:
    """
    Client for accessing Databricks Unity Catalog via PyIceberg.

    Uses the Databricks Iceberg REST API endpoint:
        {workspace_host}/api/2.1/unity-catalog/iceberg-rest

    Authentication methods (in order of precedence):
    1. Explicit token parameter
    2. DATABRICKS_TOKEN environment variable
    3. Entra ID Service Principal (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
    4. Databricks SDK default auth (Azure CLI, etc.)

    Example:
        >>> client = IcebergCatalogClient(
        ...     workspace_host="https://adb-123.10.azuredatabricks.net",
        ...     catalog_name="main"
        ... )
        >>> table = client.load_table("my_schema", "my_table")
        >>> print(table.metadata_location)
    """

    # REST API endpoint path (note: iceberg-rest with hyphen)
    ICEBERG_REST_ENDPOINT = "/api/2.1/unity-catalog/iceberg-rest"

    def __init__(
        self,
        workspace_host: str,
        catalog_name: str,
        token: Optional[str] = None,
    ):
        """
        Initialize the catalog client.

        Args:
            workspace_host: Databricks workspace URL (e.g., https://adb-xxx.azuredatabricks.net)
            catalog_name: Unity Catalog name to connect to
            token: Databricks PAT or OAuth token. If None, will attempt other auth methods.
        """
        # Databricks Apps injects DATABRICKS_HOST without a scheme
        if not workspace_host.startswith(("https://", "http://")):
            workspace_host = f"https://{workspace_host}"
        self.workspace_host = workspace_host.rstrip("/")
        self.catalog_name = catalog_name
        self._token = token
        self._catalog = None

    @property
    def token(self) -> str:
        """
        Get authentication token using multiple methods.

        Order of precedence:
        1. Explicit token (passed to constructor)
        2. DATABRICKS_TOKEN environment variable
        3. Entra ID Service Principal (OAuth client credentials)
        4. Databricks SDK (Azure CLI, managed identity, etc.)
        """
        if self._token:
            return self._token

        # Try DATABRICKS_TOKEN env var
        env_token = os.getenv("DATABRICKS_TOKEN")
        if env_token:
            self._token = env_token
            return self._token

        # Try Entra ID Service Principal
        token = self._get_entra_id_token()
        if token:
            self._token = token
            return self._token

        # Try Databricks SDK
        token = self._get_databricks_sdk_token()
        if token:
            self._token = token
            return self._token

        raise ValueError(
            "No authentication token available. Options:\n"
            "  1. Pass token parameter\n"
            "  2. Set DATABRICKS_TOKEN environment variable\n"
            "  3. Set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID for Entra ID SP\n"
            "  4. Run 'az login' for Azure CLI auth"
        )

    def _get_entra_id_token(self) -> Optional[str]:
        """
        Get OAuth token using Entra ID Service Principal.

        Requires environment variables:
        - AZURE_CLIENT_ID: Application (client) ID
        - AZURE_CLIENT_SECRET: Client secret
        - AZURE_TENANT_ID: Directory (tenant) ID

        Returns:
            OAuth access token for Databricks, or None if credentials not available
        """
        client_id = os.getenv("AZURE_CLIENT_ID")
        client_secret = os.getenv("AZURE_CLIENT_SECRET")
        tenant_id = os.getenv("AZURE_TENANT_ID")

        if not all([client_id, client_secret, tenant_id]):
            return None

        try:
            from azure.identity import ClientSecretCredential

            # Databricks resource ID for Azure
            # This is the Application ID URI for Azure Databricks
            databricks_resource_id = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"

            credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )

            # Get token for Databricks
            token = credential.get_token(f"{databricks_resource_id}/.default")
            return token.token

        except ImportError:
            print("azure-identity not installed. Install with: pip install azure-identity")
            return None
        except Exception as e:
            print(f"Entra ID authentication failed: {e}")
            return None

    def _get_databricks_sdk_token(self) -> Optional[str]:
        """Get token from Databricks SDK (supports Azure CLI, managed identity, etc.)."""
        try:
            from databricks.sdk import WorkspaceClient

            w = WorkspaceClient(host=self.workspace_host)

            # Try PAT token first
            if w.config.token:
                return w.config.token

            # Try to get token from auth headers (OIDC, etc.)
            auth_headers = w.config.authenticate()
            if isinstance(auth_headers, dict):
                auth_val = auth_headers.get("Authorization", "")
                if auth_val.startswith("Bearer "):
                    return auth_val.split(" ")[1]

        except Exception:
            pass

        return None

    @property
    def catalog(self):
        """Get or create PyIceberg catalog instance."""
        if self._catalog is None:
            try:
                from pyiceberg.catalog import load_catalog
            except ImportError:
                raise ImportError(
                    "PyIceberg is required. Install with: pip install pyiceberg"
                )

            catalog_config = {
                "uri": f"{self.workspace_host}{self.ICEBERG_REST_ENDPOINT}",
                "warehouse": self.catalog_name,
                "token": self.token,
                "type": "rest",
            }

            self._catalog = load_catalog("unity_catalog", **catalog_config)

        return self._catalog

    def load_table(self, schema_name: str, table_name: str) -> TableInfo:
        """
        Load an Iceberg table from Unity Catalog.

        Args:
            schema_name: Schema containing the table
            table_name: Name of the table

        Returns:
            TableInfo with metadata location and properties
        """
        table = self.catalog.load_table(f"{schema_name}.{table_name}")

        return TableInfo(
            name=table_name,
            schema=schema_name,
            catalog=self.catalog_name,
            metadata_location=table.metadata_location,
            properties=dict(table.properties) if table.properties else {},
        )

    def list_tables(self, schema_name: str) -> List[str]:
        """
        List all tables in a schema.

        Args:
            schema_name: Schema to list tables from

        Returns:
            List of table names
        """
        tables = self.catalog.list_tables(schema_name)
        return [t[1] for t in tables]  # Returns (namespace, name) tuples

    def list_namespaces(self) -> List[str]:
        """
        List all schemas (namespaces) in the catalog.

        Returns:
            List of schema names
        """
        namespaces = self.catalog.list_namespaces()
        return [n[0] for n in namespaces]  # Returns (namespace,) tuples

    def get_metadata_location(self, schema_name: str, table_name: str) -> str:
        """
        Get the metadata.json location for a table.

        This is useful for configuring Snowflake external volume tables
        that need the metadata file path.

        Args:
            schema_name: Schema containing the table
            table_name: Name of the table

        Returns:
            Full path to metadata.json file
        """
        table_info = self.load_table(schema_name, table_name)
        return table_info.metadata_location


def main():
    """CLI entry point for catalog client."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Query Databricks Unity Catalog via PyIceberg"
    )
    parser.add_argument(
        "--workspace-host",
        default=os.getenv("DATABRICKS_HOST"),
        help="Databricks workspace URL",
    )
    parser.add_argument(
        "--catalog",
        required=True,
        help="Unity Catalog name",
    )
    parser.add_argument(
        "--schema",
        help="Schema name (for listing tables or loading table)",
    )
    parser.add_argument(
        "--table",
        help="Table name (requires --schema)",
    )
    parser.add_argument(
        "--list-schemas",
        action="store_true",
        help="List all schemas in the catalog",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="List all tables in the schema (requires --schema)",
    )

    args = parser.parse_args()

    if not args.workspace_host:
        print("Error: --workspace-host or DATABRICKS_HOST required")
        return 1

    client = IcebergCatalogClient(
        workspace_host=args.workspace_host,
        catalog_name=args.catalog,
    )

    try:
        if args.list_schemas:
            print(f"Schemas in {args.catalog}:")
            for schema in client.list_namespaces():
                print(f"  - {schema}")

        elif args.list_tables:
            if not args.schema:
                print("Error: --schema required with --list-tables")
                return 1
            print(f"Tables in {args.catalog}.{args.schema}:")
            for table in client.list_tables(args.schema):
                print(f"  - {table}")

        elif args.table:
            if not args.schema:
                print("Error: --schema required with --table")
                return 1
            table_info = client.load_table(args.schema, args.table)
            print(f"Table: {args.catalog}.{args.schema}.{args.table}")
            print(f"Metadata: {table_info.metadata_location}")

        else:
            parser.print_help()

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
