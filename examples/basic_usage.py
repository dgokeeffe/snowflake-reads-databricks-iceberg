#!/usr/bin/env python3
"""
Basic usage example for snowflake-databricks-iceberg.

This demonstrates the enterprise pattern for enabling Snowflake
to read Iceberg tables from Databricks Unity Catalog.

Prerequisites:
1. Set environment variables (or use .env file):
   - DATABRICKS_HOST: Your Databricks workspace URL
   - DATABRICKS_TOKEN: PAT token (or use Entra ID SP)
   - SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, etc.

2. For Entra ID authentication (recommended for enterprise):
   - AZURE_CLIENT_ID: Application (client) ID
   - AZURE_CLIENT_SECRET: Client secret
   - AZURE_TENANT_ID: Directory (tenant) ID
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def main():
    """Demonstrate the end-to-end workflow."""
    from snowflake_databricks_iceberg import (
        IcebergCatalogClient,
        CatalogIntegration,
        ExternalVolume,
        TableRefresher,
    )

    # Configuration
    databricks_host = os.getenv("DATABRICKS_HOST")
    databricks_catalog = "main"
    databricks_schema = "tpcds_sf1"

    snowflake_db = "TPCDS_DB"
    snowflake_schema = "ICEBERG"

    azure_storage_account = os.getenv("AZURE_STORAGE_ACCOUNT")
    azure_container = os.getenv("AZURE_CONTAINER", "unity-catalog")

    # Step 1: Use PyIceberg to discover tables from Databricks
    # This runs in YOUR network, not Snowflake's
    print("Step 1: Discovering tables via PyIceberg...")
    client = IcebergCatalogClient(
        workspace_host=databricks_host,
        catalog_name=databricks_catalog,
    )

    tables = client.list_tables(databricks_schema)
    print(f"  Found {len(tables)} tables in {databricks_catalog}.{databricks_schema}")

    # Show metadata location for one table
    if tables:
        table_info = client.load_table(databricks_schema, tables[0])
        print(f"  Example metadata: {table_info.metadata_location}")

    # Step 2: Ensure Snowflake has OBJECT_STORE Catalog Integration
    # This is REQUIRED for all Iceberg tables
    print("\nStep 2: Setting up Catalog Integration...")
    catalog_int = CatalogIntegration()

    catalog_int_name = "iceberg_object_store"
    result = catalog_int.create_object_store(catalog_int_name)
    print(f"  {result}")

    # Step 3: Create External Volume for Azure storage access
    print("\nStep 3: Setting up External Volume...")
    volume = ExternalVolume(
        volume_name="databricks_iceberg_vol",
        storage_account=azure_storage_account,
        container=azure_container,
        base_path="root/",  # Unity Catalog default path
    )

    # Note: This requires Azure consent flow
    # volume.create()

    # Step 4: Refresh Snowflake tables from Databricks metadata
    print("\nStep 4: Refreshing tables...")
    refresher = TableRefresher(
        databricks_catalog=databricks_catalog,
        databricks_schema=databricks_schema,
        snowflake_db=snowflake_db,
        snowflake_schema=snowflake_schema,
        external_volume="databricks_iceberg_vol",
    )

    try:
        # This creates/updates Iceberg tables in Snowflake
        results = refresher.refresh_all(parallel=2)
        print(f"  Refreshed {len(results)} tables")
        for table, success in results.items():
            status = "OK" if success else "FAILED"
            print(f"    {table}: {status}")
    finally:
        refresher.close()

    print("\nDone! Snowflake can now query Databricks Iceberg tables.")


if __name__ == "__main__":
    main()
