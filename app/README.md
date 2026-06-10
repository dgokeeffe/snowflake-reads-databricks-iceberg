# Refresh demo app

A one-page Databricks App that makes the manual-refresh pattern visible:

1. **Write 1,000 rows** into a Unity Catalog managed Iceberg table (Databricks).
2. The Snowflake count card shows it is **behind** — Snowflake still points at the
   old `metadata.json`.
3. **Refresh Snowflake** — PyIceberg discovers the latest metadata path via the UC
   Iceberg REST API and runs `ALTER ICEBERG TABLE … REFRESH '<path>'`.
4. Both counts match. One copy of data, two engines.

## Local dev

```bash
# backend (from app/)
uv venv && uv pip install -r requirements.txt
cp ../.env .  # or set SNOWFLAKE_*, DATABRICKS_HOST, DEMO_* vars
uv run uvicorn backend.main:app --reload --port 8000

# frontend (separate shell)
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api
```

## Deploy as a Databricks App

```bash
cd frontend && npm install && npm run build && cd ..   # emits backend/static/
databricks secrets create-scope iceberg-demo
databricks secrets put-secret iceberg-demo snowflake-password
databricks apps create iceberg-refresh-demo
databricks sync . "/Users/<you>/iceberg-refresh-demo" --full
databricks apps deploy iceberg-refresh-demo --source-code-path "/Workspace/Users/<you>/iceberg-refresh-demo"
```

Adjust `app.yaml` env values (catalog, Snowflake account, external volume) to your
environment. The app's service principal needs `USE CATALOG`/`USE SCHEMA`/`CREATE TABLE`/
`SELECT`/`MODIFY` on the demo catalog+schema and `CAN USE` on a SQL warehouse.
Snowflake-side, the external volume + OBJECT_STORE catalog integration must already
exist (see the repo root README / terraform).

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `DEMO_CATALOG` / `DEMO_SCHEMA` / `DEMO_TABLE` | `main.iceberg_demo.demo_events` | UC Iceberg table the demo writes |
| `DEMO_SNOWFLAKE_DB` / `DEMO_SNOWFLAKE_SCHEMA` | `ICEBERG_DEMO.PUBLIC` | Snowflake side of the table |
| `SNOWFLAKE_EXTERNAL_VOLUME` | `databricks_uniform_volume` | Existing external volume over the UC storage account |
| `SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` / `SNOWFLAKE_PASSWORD` / `SNOWFLAKE_WAREHOUSE` | — | Snowflake connection |
| `DATABRICKS_WAREHOUSE_ID` | first warehouse | SQL warehouse for writes/counts |
