# Snowflake-Databricks Iceberg Integration

Enable Snowflake to read Apache Iceberg tables from Databricks Unity Catalog using PyIceberg for metadata discovery.

## Why This Approach?

In enterprise environments, Snowflake often cannot directly reach Databricks Unity Catalog over private networks. This package solves that by:

1. **PyIceberg** (runs in your network) connects to Databricks UC Iceberg REST API
2. **Discovers** the latest `metadata.json` paths for each table
3. **Snowflake** reads tables via External Volume + `OBJECT_STORE` Catalog Integration

This keeps all network traffic within your control:
- PyIceberg → Databricks: Your private network / VNet
- Snowflake → Azure Storage: Azure Private Link capable

```
┌─────────────────┐                              ┌─────────────────────┐
│  Your Network   │      Private Network         │    DATABRICKS       │
│                 │ ───────────────────────────► │    Unity Catalog    │
│  ┌───────────┐  │                              │    Iceberg REST API │
│  │ PyIceberg │  │  GET metadata.json paths     │                     │
│  │ Client    │  │ ◄─────────────────────────── │  /api/2.1/unity-    │
│  └─────┬─────┘  │                              │  catalog/iceberg-   │
│        │        │                              │  rest               │
└────────┼────────┘                              └─────────────────────┘
         │
         │ Update Snowflake tables
         │ with metadata paths
         ▼
┌─────────────────┐                              ┌─────────────────────┐
│   SNOWFLAKE     │      Azure Private Link      │  AZURE STORAGE      │
│                 │ ───────────────────────────► │  (ADLS Gen2)        │
│  CATALOG_SOURCE │                              │                     │
│  = OBJECT_STORE │  Read Iceberg data files     │  metadata.json      │
│                 │ ◄─────────────────────────── │  *.parquet          │
│  External Volume│                              │                     │
└─────────────────┘                              └─────────────────────┘
```

## The Azure storage path limitation (why this method exists)

Azure Data Lake Storage Gen2 exposes a **single** storage account through **two** DNS
endpoints. They address the same bytes, but they are *not* interchangeable strings, and
Databricks and Snowflake each speak only one of them:

| Endpoint | API surface | Used by | URL scheme |
|----------|-------------|---------|------------|
| `<account>.dfs.core.windows.net` | ADLS Gen2 / ABFS (hierarchical namespace) | Databricks | `abfss://…` |
| `<account>.blob.core.windows.net` | Blob REST API | Snowflake | `azure://…` |

- **Databricks** records every Iceberg table's current metadata pointer as an absolute
  **`dfs`** URL. The Unity Catalog Iceberg REST API returns, for example:

  ```
  abfss://container@account.dfs.core.windows.net/root/__unitystorage/.../metadata/00007-uuid.metadata.json
  ```

- **Snowflake** external volumes on Azure are defined against the **Blob** endpoint via the
  `azure://` scheme, and Snowflake does **not** accept `abfss://` or `dfs.core.windows.net`
  in an external volume or in `METADATA_FILE_PATH`:

  ```sql
  STORAGE_BASE_URL = 'azure://account.blob.core.windows.net/container/root/'
  ```

So **you cannot hand Snowflake the path Databricks gives you.** The absolute `dfs` URL is
meaningless to Snowflake's Iceberg reader, which only resolves files *relative to* its
Blob-based external volume base. This package bridges the gap by converting the Databricks
`abfss://…/root/<path>` URL into a path relative to the external volume's `STORAGE_BASE_URL`
— stripping the scheme, account host, container, and the shared `root/` prefix:

```
abfss://container@account.dfs.core.windows.net/root/__unitystorage/.../00007-uuid.metadata.json
                                                    └────────────────────────┬────────────────────────┘
                                                                             ▼
                            METADATA_FILE_PATH = '__unitystorage/.../00007-uuid.metadata.json'
```

(See `TableRefresher.convert_abfss_to_snowflake_path()`.)

### Why this also forces a *manual* refresh

Because the value Snowflake stores is a **literal, relative metadata-file path** — not a live
catalog reference — Snowflake has no way to discover that Databricks has written a newer
`metadata.json`. Every Databricks commit (INSERT / MERGE / OPTIMIZE / schema change) produces
a new `NNNNN-uuid.metadata.json`; until you re-point Snowflake at it, queries return stale data.
Closing that gap is the entire job of this package:

1. Ask Databricks (via PyIceberg) for the **current** `metadata_location`.
2. Convert the `dfs` URL to a Blob-relative path.
3. `ALTER ICEBERG TABLE … REFRESH '<relative-path>'` (or `CREATE` on first run).

> **What about `CATALOG_SOURCE = ICEBERG_REST` + `AUTO_REFRESH`?** Snowflake's managed REST
> integration *can* auto-refresh, but it requires Snowflake's own infrastructure to reach the
> Databricks REST API and to reconcile the `dfs`-style locations that catalog vends — neither
> of which is dependable in a private-network Azure setup. See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#why-not-iceberg_rest). The `OBJECT_STORE` +
> relative-path method sidesteps both by keeping path resolution entirely on the Snowflake
> side, against a Blob external volume you control.

## Quick Start

### Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Using pip
pip install -e .
```

### Environment Variables

```bash
# .env file
DATABRICKS_HOST=https://adb-123456789.10.azuredatabricks.net
DATABRICKS_TOKEN=dapi...  # Or use Azure CLI auth

SNOWFLAKE_ACCOUNT=ORGNAME-ACCOUNTNAME
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=COMPUTE_WH

AZURE_TENANT_ID=your-tenant-id  # Optional, auto-detected from Azure CLI
```

## Usage

### Step 1: Create External Volume in Snowflake

The External Volume provides Snowflake access to Azure Storage where your Iceberg data lives.

```bash
python -m snowflake_databricks_iceberg.external_volume \
  --volume-name databricks_iceberg_volume \
  --storage-base-path root/
```

This will:
1. Create the External Volume
2. Open Azure consent URL (grant admin consent)
3. Assign Storage Blob Data Contributor role to Snowflake's service principal
4. Create the required `OBJECT_STORE` Catalog Integration

### Step 2: Refresh Tables Using PyIceberg

PyIceberg connects to Databricks UC to get the latest metadata paths, then creates/refreshes Snowflake tables.

```bash
python -m snowflake_databricks_iceberg.table_refresher \
  --catalog main \
  --schema my_iceberg_schema \
  --snowflake-db MY_DATABASE \
  --snowflake-schema MY_SCHEMA \
  --external-volume databricks_iceberg_volume
```

This will:
1. Connect to Databricks via PyIceberg REST client
2. List all tables in the schema
3. Get `metadata.json` location for each table
4. Create or refresh Snowflake Iceberg tables

### Step 3: Query in Snowflake

```sql
-- Tables are now queryable
SELECT * FROM MY_DATABASE.MY_SCHEMA.my_table LIMIT 10;

-- Check table metadata
DESC ICEBERG TABLE my_table;
```

## Python API

### PyIceberg Catalog Client

```python
from snowflake_databricks_iceberg import IcebergCatalogClient

# Connect to Unity Catalog
client = IcebergCatalogClient(
    workspace_host="https://adb-xxx.azuredatabricks.net",
    catalog_name="main"
)

# List tables
tables = client.list_tables("my_schema")

# Get metadata location (for Snowflake refresh)
for table_name in tables:
    metadata_path = client.get_metadata_location("my_schema", table_name)
    print(f"{table_name}: {metadata_path}")
```

### Catalog Integration

```python
from snowflake_databricks_iceberg import CatalogIntegration

# Create OBJECT_STORE catalog integration (REQUIRED for Iceberg)
integration = CatalogIntegration()
integration.create_object_store("my_volume_catalog")
```

### Table Refresher

```python
from snowflake_databricks_iceberg import TableRefresher

refresher = TableRefresher(
    databricks_catalog="main",
    databricks_schema="my_schema",
    snowflake_db="MY_DB",
    snowflake_schema="MY_SCHEMA",
    external_volume="my_volume"
)

# Refresh all tables
results = refresher.refresh_all()

# Or refresh a single table
refresher.refresh_table("my_table", "path/to/metadata.json")
```

## Snowflake Components

### Catalog Integration (Required)

Snowflake requires a Catalog Integration for ALL Iceberg tables:

```sql
-- This is created automatically by the external_volume module
CREATE CATALOG INTEGRATION databricks_iceberg_volume_catalog
  CATALOG_SOURCE = OBJECT_STORE
  TABLE_FORMAT = ICEBERG
  ENABLED = TRUE;
```

### External Volume

```sql
-- Created by the external_volume module
CREATE EXTERNAL VOLUME databricks_iceberg_volume
  STORAGE_LOCATIONS = (
    (
      NAME = 'azure_storage'
      STORAGE_PROVIDER = 'AZURE'
      STORAGE_BASE_URL = 'azure://account.blob.core.windows.net/container/root/'
      AZURE_TENANT_ID = 'your-tenant-id'
    )
  );
```

### Iceberg Tables

```sql
-- Tables are created/refreshed by the table_refresher module
CREATE ICEBERG TABLE my_table
  EXTERNAL_VOLUME = 'databricks_iceberg_volume'
  CATALOG = 'databricks_iceberg_volume_catalog'
  METADATA_FILE_PATH = '__unitystorage/.../metadata/00001-xxx.metadata.json';

-- Manual refresh when data changes
ALTER ICEBERG TABLE my_table REFRESH 'path/to/new-metadata.json';
```

## Automating Refresh

Since this is a manual refresh approach, you'll want to automate it. Options:

### 1. Scheduled Job (Databricks Workflow)

```python
# Run as a Databricks job on schedule
from snowflake_databricks_iceberg import TableRefresher

refresher = TableRefresher(...)
refresher.refresh_all()
```

### 2. Airflow DAG

```python
from airflow.operators.python import PythonOperator

def refresh_snowflake_tables():
    from snowflake_databricks_iceberg import TableRefresher
    refresher = TableRefresher(...)
    refresher.refresh_all()

refresh_task = PythonOperator(
    task_id='refresh_snowflake_iceberg',
    python_callable=refresh_snowflake_tables,
)
```

### 3. Delta Live Tables Post-Hook

After your DLT pipeline completes, trigger a refresh.

## Architecture Details

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed diagrams.

### Key Points

1. **PyIceberg REST Endpoint**: `{workspace}/api/2.1/unity-catalog/iceberg-rest` (note the hyphen)
2. **Catalog Integration**: `CATALOG_SOURCE = OBJECT_STORE` is required for External Volume method
3. **Metadata Path**: Relative to External Volume's `STORAGE_BASE_URL`
4. **UniForm Tables**: Metadata is under `__unitystorage/.../<table_id>/metadata/`

## Terraform

Optional Terraform modules are provided in `terraform/` for:
- Snowflake Storage Integration
- Azure RBAC assignments
- Service Principal lookup

## Requirements

- Python 3.10+
- Databricks workspace with Unity Catalog
- Snowflake account (ACCOUNTADMIN for creating integrations)
- Azure Storage Account (ADLS Gen2)

## License

Apache License 2.0
