"""
Command-line interface for snowflake-databricks-iceberg.

Enterprise approach for Snowflake to read Databricks Iceberg tables:
1. PyIceberg (your network) → Databricks UC Iceberg REST API
2. Snowflake → Azure Storage (via External Volume + OBJECT_STORE Catalog Integration)
"""

import argparse
import sys


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="snowflake-databricks-iceberg",
        description="Enable Snowflake to read Iceberg tables from Databricks Unity Catalog",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # External volume command
    volume_parser = subparsers.add_parser(
        "external-volume",
        help="Create external volume for Azure storage",
    )
    volume_parser.add_argument(
        "--volume-name",
        required=True,
        help="External volume name",
    )
    volume_parser.add_argument("--storage-account", help="Azure storage account")
    volume_parser.add_argument("--container", help="Azure container name")
    volume_parser.add_argument(
        "--base-path",
        default="root/",
        help="Base path in container",
    )
    volume_parser.add_argument("--auto-consent", action="store_true")
    volume_parser.add_argument("--no-verify", action="store_true")

    # Refresh tables command
    refresh_parser = subparsers.add_parser(
        "refresh-tables",
        help="Refresh Snowflake tables from Unity Catalog",
    )
    refresh_parser.add_argument("--catalog", required=True, help="Databricks catalog")
    refresh_parser.add_argument("--schema", required=True, help="Databricks schema")
    refresh_parser.add_argument(
        "--snowflake-db",
        required=True,
        help="Snowflake database",
    )
    refresh_parser.add_argument(
        "--snowflake-schema",
        required=True,
        help="Snowflake schema",
    )
    refresh_parser.add_argument(
        "--external-volume",
        required=True,
        help="External volume name",
    )
    refresh_parser.add_argument(
        "--parallel",
        type=int,
        default=2,
        help="Parallel workers",
    )

    # List tables command
    list_parser = subparsers.add_parser(
        "list-tables",
        help="List tables via PyIceberg",
    )
    list_parser.add_argument("--catalog", required=True, help="Unity Catalog name")
    list_parser.add_argument("--schema", help="Schema name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "external-volume":
        from snowflake_databricks_iceberg.external_volume import ExternalVolume

        volume = ExternalVolume(
            volume_name=args.volume_name,
            storage_account=args.storage_account,
            container=args.container,
            base_path=args.base_path,
        )

        if volume.create(auto_consent=args.auto_consent):
            if not args.no_verify:
                volume.verify()

    elif args.command == "refresh-tables":
        from snowflake_databricks_iceberg.table_refresher import TableRefresher

        refresher = TableRefresher(
            databricks_catalog=args.catalog,
            databricks_schema=args.schema,
            snowflake_db=args.snowflake_db,
            snowflake_schema=args.snowflake_schema,
            external_volume=args.external_volume,
        )

        try:
            results = refresher.refresh_all(parallel=args.parallel)
            if not results or any(not v for v in results.values()):
                return 1
        finally:
            refresher.close()

    elif args.command == "list-tables":
        from snowflake_databricks_iceberg.catalog_client import IcebergCatalogClient
        import os

        client = IcebergCatalogClient(
            workspace_host=os.getenv("DATABRICKS_HOST"),
            catalog_name=args.catalog,
        )

        if args.schema:
            tables = client.list_tables(args.schema)
            print(f"Tables in {args.catalog}.{args.schema}:")
            for t in tables:
                print(f"  - {t}")
        else:
            schemas = client.list_namespaces()
            print(f"Schemas in {args.catalog}:")
            for s in schemas:
                print(f"  - {s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
