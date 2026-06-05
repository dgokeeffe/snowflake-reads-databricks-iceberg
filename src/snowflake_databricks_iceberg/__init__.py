"""
Snowflake-Databricks Iceberg Integration

Enable Snowflake to read Apache Iceberg tables from Databricks Unity Catalog
using PyIceberg for metadata discovery.

Enterprise Architecture:
    - PyIceberg (your network) → Databricks UC Iceberg REST API
    - Snowflake → Azure Storage (via External Volume + OBJECT_STORE Catalog Integration)

Key Components:
    - IcebergCatalogClient: PyIceberg client for Unity Catalog REST API
    - CatalogIntegration: REQUIRED for all Iceberg tables in Snowflake
    - ExternalVolume: Snowflake access to Azure Blob Storage
    - TableRefresher: Sync Snowflake tables with Unity Catalog metadata

Authentication:
    - Entra ID Service Principal (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
    - Databricks PAT token (DATABRICKS_TOKEN)
    - Azure CLI (az login)
"""

from snowflake_databricks_iceberg.catalog_client import IcebergCatalogClient
from snowflake_databricks_iceberg.catalog_integration import (
    CatalogIntegration,
    CatalogSource,
)
from snowflake_databricks_iceberg.external_volume import ExternalVolume
from snowflake_databricks_iceberg.table_refresher import TableRefresher

__version__ = "0.1.0"

__all__ = [
    "IcebergCatalogClient",
    "CatalogIntegration",
    "CatalogSource",
    "ExternalVolume",
    "TableRefresher",
]
