# Architecture: Snowflake Reading Databricks Iceberg Tables

## Enterprise Architecture

This approach is designed for enterprise environments where Snowflake cannot directly reach Databricks over private networks.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        ENTERPRISE ARCHITECTURE                                          │
│                                                                                         │
│   PyIceberg runs in YOUR network (VNet/Private) - YOU control this connection          │
│   Snowflake accesses Azure Storage (can use Private Link) - No Databricks access       │
└─────────────────────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│   YOUR NETWORK / VNET                                                                   │
│   ══════════════════                                                                    │
│                                                                                         │
│   ┌─────────────────────────────────────────────┐                                      │
│   │                                             │                                      │
│   │   ┌─────────────────────────────────────┐   │                                      │
│   │   │         PYICEBERG CLIENT            │   │                                      │
│   │   │                                     │   │                                      │
│   │   │  from pyiceberg.catalog import      │   │                                      │
│   │   │      load_catalog                   │   │                                      │
│   │   │                                     │   │                                      │
│   │   │  catalog = load_catalog("uc", **{   │   │                                      │
│   │   │    "uri": "{host}/api/2.1/unity-    │   │                                      │
│   │   │           catalog/iceberg-rest",    │   │                                      │
│   │   │    "warehouse": "main",             │   │                                      │
│   │   │    "token": "<token>",              │   │                                      │
│   │   │    "type": "rest"                   │   │                                      │
│   │   │  })                                 │   │                                      │
│   │   │                                     │   │                                      │
│   │   │  table = catalog.load_table(        │   │                                      │
│   │   │      "schema.table")                │   │                                      │
│   │   │  metadata_path = table.             │   │                                      │
│   │   │      metadata_location              │   │                                      │
│   │   │                                     │   │                                      │
│   │   └──────────────┬──────────────────────┘   │                                      │
│   │                  │                          │                                      │
│   │                  │ REST API                 │                                      │
│   │                  │ (Private Endpoint        │                                      │
│   │                  │  or VNet Injection)      │                                      │
│   │                  │                          │                                      │
│   └──────────────────┼──────────────────────────┘                                      │
│                      │                                                                  │
└──────────────────────┼──────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│   DATABRICKS UNITY CATALOG                                                              │
│   ════════════════════════                                                              │
│                                                                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│   │                                                                                  │  │
│   │   ICEBERG REST API                                                              │  │
│   │   ════════════════                                                              │  │
│   │                                                                                  │  │
│   │   Endpoint: /api/2.1/unity-catalog/iceberg-rest                                 │  │
│   │                                     ▲                                            │  │
│   │                                     │                                            │  │
│   │   Note: "iceberg-rest" with hyphen ─┘                                           │  │
│   │                                                                                  │  │
│   │   Returns:                                                                       │  │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │  │
│   │   │ {                                                                       │    │  │
│   │   │   "metadata_location": "abfss://container@account.dfs.core.windows.net │    │  │
│   │   │                         /root/__unitystorage/.../metadata/00001-xxx.   │    │  │
│   │   │                         metadata.json"                                  │    │  │
│   │   │ }                                                                       │    │  │
│   │   └────────────────────────────────────────────────────────────────────────┘    │  │
│   │                                                                                  │  │
│   └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│   │                                                                                  │  │
│   │   UNITY CATALOG TABLES                                                          │  │
│   │   ════════════════════                                                          │  │
│   │                                                                                  │  │
│   │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                │  │
│   │   │  Delta + UniForm│  │  Native Iceberg │  │  Managed Tables │                │  │
│   │   │                 │  │                 │  │                 │                │  │
│   │   │  Iceberg compat │  │  Pure Iceberg   │  │  UC Managed     │                │  │
│   │   │  metadata layer │  │  format         │  │  storage        │                │  │
│   │   └─────────────────┘  └─────────────────┘  └─────────────────┘                │  │
│   │                                                                                  │  │
│   └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                       │
                       │ Metadata points to storage location
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│   AZURE BLOB STORAGE (ADLS Gen2)                                                        │
│   ══════════════════════════════                                                        │
│                                                                                         │
│   URL: abfss://container@storageaccount.dfs.core.windows.net/                          │
│                                                                                         │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│   │                                                                                  │  │
│   │   root/                                                                          │  │
│   │     └── __unitystorage/                   ◄── Unity Catalog managed path        │  │
│   │           └── <catalog_guid>/                                                    │  │
│   │                 └── <schema_guid>/                                               │  │
│   │                       └── <table_guid>/                                          │  │
│   │                             │                                                    │  │
│   │                             ├── metadata/                                        │  │
│   │                             │     ├── 00000-uuid.metadata.json                  │  │
│   │                             │     ├── 00001-uuid.metadata.json  ◄── LATEST     │  │
│   │                             │     ├── snap-12345-uuid.avro                      │  │
│   │                             │     └── ...                                        │  │
│   │                             │                                                    │  │
│   │                             └── data/                                            │  │
│   │                                   ├── part-00000-uuid.snappy.parquet            │  │
│   │                                   ├── part-00001-uuid.snappy.parquet            │  │
│   │                                   └── ...                                        │  │
│   │                                                                                  │  │
│   └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
│                                         ▲                                               │
│                                         │                                               │
│                                         │ Azure Private Link (optional)                │
│                                         │ OR Public with Storage Firewall              │
│                                         │                                               │
└─────────────────────────────────────────┼───────────────────────────────────────────────┘
                                          │
                                          │
┌─────────────────────────────────────────┼───────────────────────────────────────────────┐
│                                         │                                               │
│   SNOWFLAKE                             │                                               │
│   ═════════                             │                                               │
│                                         │                                               │
│   ┌─────────────────────────────────────┴───────────────────────────────────────────┐  │
│   │                                                                                  │  │
│   │   EXTERNAL VOLUME                                                               │  │
│   │   ═══════════════                                                               │  │
│   │                                                                                  │  │
│   │   CREATE EXTERNAL VOLUME databricks_iceberg_volume                              │  │
│   │     STORAGE_LOCATIONS = (                                                        │  │
│   │       (                                                                          │  │
│   │         NAME = 'azure_storage'                                                   │  │
│   │         STORAGE_PROVIDER = 'AZURE'                                               │  │
│   │         STORAGE_BASE_URL = 'azure://account.blob.core.windows.net/              │  │
│   │                            container/root/'                                      │  │
│   │         AZURE_TENANT_ID = '<tenant_id>'                                          │  │
│   │       )                                                                          │  │
│   │     );                                                                           │  │
│   │                                                                                  │  │
│   │   Authentication: Azure AD Service Principal (created by Snowflake)             │  │
│   │   Roles Required: Storage Blob Data Contributor                                  │  │
│   │                                                                                  │  │
│   └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
│   ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│   │                                                                                  │  │
│   │   CATALOG INTEGRATION (REQUIRED)                                                │  │
│   │   ══════════════════════════════                                                │  │
│   │                                                                                  │  │
│   │   CREATE CATALOG INTEGRATION databricks_iceberg_volume_catalog                  │  │
│   │     CATALOG_SOURCE = OBJECT_STORE    ◄── Direct storage access                  │  │
│   │     TABLE_FORMAT = ICEBERG                                                       │  │
│   │     ENABLED = TRUE;                                                              │  │
│   │                                                                                  │  │
│   │   Note: This is REQUIRED for ALL Iceberg tables in Snowflake                    │  │
│   │                                                                                  │  │
│   └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
│   ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│   │                                                                                  │  │
│   │   ICEBERG TABLES                                                                │  │
│   │   ══════════════                                                                │  │
│   │                                                                                  │  │
│   │   CREATE ICEBERG TABLE my_table                                                 │  │
│   │     EXTERNAL_VOLUME = 'databricks_iceberg_volume'                               │  │
│   │     CATALOG = 'databricks_iceberg_volume_catalog'                               │  │
│   │     METADATA_FILE_PATH = '__unitystorage/.../metadata/00001-xxx.metadata.json'; │  │
│   │                          ▲                                                       │  │
│   │                          │                                                       │  │
│   │                          └── Path from PyIceberg (relative to External Volume)  │  │
│   │                                                                                  │  │
│   │   -- Refresh when data changes                                                  │  │
│   │   ALTER ICEBERG TABLE my_table REFRESH 'new/metadata/path.json';                │  │
│   │                                                                                  │  │
│   └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow Sequence

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              REFRESH FLOW SEQUENCE                                      │
└─────────────────────────────────────────────────────────────────────────────────────────┘

   Step 1: PyIceberg Gets Metadata Location
   ═════════════════════════════════════════

   ┌──────────────┐                           ┌──────────────────┐
   │              │  REST: GET table metadata │                  │
   │   PyIceberg  │ ────────────────────────► │  Databricks UC   │
   │   Client     │                           │  Iceberg REST    │
   │              │  Response: metadata_loc   │                  │
   │              │ ◄──────────────────────── │                  │
   └──────┬───────┘                           └──────────────────┘
          │
          │  metadata_location = "abfss://container@account/root/__unitystorage/
          │                       .../metadata/00001-xxx.metadata.json"
          │
          ▼
   Step 2: Convert Path for Snowflake
   ═══════════════════════════════════

   ┌──────────────────────────────────────────────────────────────────────────────┐
   │                                                                               │
   │   Full Path:     abfss://container@account.dfs.core.windows.net/root/        │
   │                  __unitystorage/.../metadata/00001-xxx.metadata.json         │
   │                                                                               │
   │   External Volume Base: azure://account.blob.core.windows.net/container/root/│
   │                                                                               │
   │   Relative Path: __unitystorage/.../metadata/00001-xxx.metadata.json         │
   │                  ▲                                                            │
   │                  └── This goes in METADATA_FILE_PATH                          │
   │                                                                               │
   └──────────────────────────────────────────────────────────────────────────────┘

          │
          ▼
   Step 3: Create/Refresh Snowflake Table
   ═══════════════════════════════════════

   ┌──────────────┐                           ┌──────────────────┐
   │              │  CREATE ICEBERG TABLE     │                  │
   │   Python     │  with METADATA_FILE_PATH  │    Snowflake     │
   │   Script     │ ────────────────────────► │                  │
   │              │                           │                  │
   │              │  Or: ALTER ... REFRESH    │                  │
   │              │ ────────────────────────► │                  │
   └──────────────┘                           └────────┬─────────┘
                                                       │
                                                       │
          ┌────────────────────────────────────────────┘
          │
          ▼
   Step 4: Snowflake Reads Data
   ════════════════════════════

   ┌──────────────────┐                       ┌──────────────────┐
   │                  │  Read metadata.json   │                  │
   │    Snowflake     │ ────────────────────► │  Azure Storage   │
   │                  │                       │                  │
   │                  │  Read parquet files   │  (via External   │
   │                  │ ────────────────────► │   Volume SP)     │
   │                  │                       │                  │
   │                  │  Query results        │                  │
   │                  │ ◄──────────────────── │                  │
   └──────────────────┘                       └──────────────────┘
```

## Why Not ICEBERG_REST?

Snowflake's `CATALOG_SOURCE = ICEBERG_REST` would require Snowflake's infrastructure to directly call the Databricks REST API. In enterprise environments:

| Concern | ICEBERG_REST | OBJECT_STORE + PyIceberg |
|---------|-------------|--------------------------|
| Network path | Snowflake → Databricks (public) | Your network → Databricks (private) |
| Private Link | ❌ Not supported | ✅ You control the connection |
| Firewall rules | Must allow Snowflake IPs | Only your IPs need access |
| Compliance | Data path through Snowflake infra | Data path through your infra |

## Components Summary

| Component | Purpose | Created By |
|-----------|---------|------------|
| **PyIceberg Client** | Get metadata.json paths from Databricks | `IcebergCatalogClient` |
| **External Volume** | Snowflake access to Azure Storage | `ExternalVolume` |
| **Catalog Integration** | Required for Iceberg tables | `CatalogIntegration` |
| **Table Refresher** | Sync Snowflake tables with metadata | `TableRefresher` |
