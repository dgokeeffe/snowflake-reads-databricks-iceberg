"""Demo Databricks App: watch Snowflake catch up to Databricks Iceberg writes.

Three endpoints drive the demo:
  POST /api/write    - insert rows into a UC managed Iceberg table (Databricks)
  POST /api/refresh  - PyIceberg metadata discovery + ALTER ICEBERG TABLE REFRESH (Snowflake)
  GET  /api/counts   - row counts from both engines, side by side

The Snowflake count lags after a write until /api/refresh re-points the
Snowflake Iceberg table at the new metadata.json - that lag IS the demo.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from snowflake_databricks_iceberg import TableRefresher

load_dotenv()

DEMO_CATALOG = os.getenv("DEMO_CATALOG", "main")
DEMO_SCHEMA = os.getenv("DEMO_SCHEMA", "iceberg_demo")
DEMO_TABLE = os.getenv("DEMO_TABLE", "demo_events")
SNOWFLAKE_DB = os.getenv("DEMO_SNOWFLAKE_DB", "ICEBERG_DEMO")
SNOWFLAKE_SCHEMA = os.getenv("DEMO_SNOWFLAKE_SCHEMA", "PUBLIC")
EXTERNAL_VOLUME = os.getenv("SNOWFLAKE_EXTERNAL_VOLUME", "databricks_uniform_volume")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID")

# RBAC add-on: two foreign catalogs over the same Snowflake table, each backed
# by a connection pinned to a different Snowflake role (see
# scripts/setup/setup_snowflake_rbac_demo.py in the benchmark project)
RBAC_PERSONAS = {
    "global": {
        "catalog": os.getenv("RBAC_CATALOG_GLOBAL", "rbac_demo_global"),
        "role": "ANALYST_GLOBAL",
        "blurb": "all rows, PII clear",
    },
    "au": {
        "catalog": os.getenv("RBAC_CATALOG_AU", "rbac_demo_au"),
        "role": "ANALYST_AU",
        "blurb": "AU rows only, PII masked by Snowflake",
    },
}
RBAC_SCHEMA = os.getenv("RBAC_SCHEMA", "sales")
RBAC_TABLE = os.getenv("RBAC_TABLE", "customer_orders")
RBAC_POLICIES = ["region_policy", "email_mask", "card_mask"]

app = FastAPI(title="Snowflake reads Databricks Iceberg - refresh demo")

_w: WorkspaceClient | None = None


def workspace() -> WorkspaceClient:
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


def warehouse_id() -> str:
    if WAREHOUSE_ID:
        return WAREHOUSE_ID
    warehouses = list(workspace().warehouses.list())
    if not warehouses:
        raise HTTPException(500, "No SQL warehouse available; set DATABRICKS_WAREHOUSE_ID")
    return warehouses[0].id


def run_dbsql(statement: str) -> list[list]:
    r = workspace().statement_execution.execute_statement(
        statement=statement, warehouse_id=warehouse_id(), wait_timeout="50s"
    )
    if r.status.state.value != "SUCCEEDED":
        msg = r.status.error.message if r.status.error else r.status.state.value
        raise HTTPException(502, f"Databricks SQL failed: {msg}")
    return r.result.data_array if r.result and r.result.data_array else []


def make_refresher() -> TableRefresher:
    return TableRefresher(
        databricks_catalog=DEMO_CATALOG,
        databricks_schema=DEMO_SCHEMA,
        snowflake_db=SNOWFLAKE_DB,
        snowflake_schema=SNOWFLAKE_SCHEMA,
        external_volume=EXTERNAL_VOLUME,
    )


FQ_TABLE = f"{DEMO_CATALOG}.{DEMO_SCHEMA}.{DEMO_TABLE}"


class WriteRequest(BaseModel):
    rows: int = 1000


@app.post("/api/write")
def write_rows(req: WriteRequest):
    rows = max(1, min(req.rows, 100_000))
    start = time.time()
    run_dbsql(f"CREATE SCHEMA IF NOT EXISTS {DEMO_CATALOG}.{DEMO_SCHEMA}")
    run_dbsql(
        f"CREATE TABLE IF NOT EXISTS {FQ_TABLE} "
        "(event_id BIGINT, event_ts TIMESTAMP, payload STRING) USING ICEBERG"
    )
    run_dbsql(
        f"INSERT INTO {FQ_TABLE} "
        f"SELECT id, current_timestamp(), uuid() FROM range({rows})"
    )
    return {"inserted": rows, "table": FQ_TABLE, "seconds": round(time.time() - start, 2)}


@app.post("/api/refresh")
def refresh_snowflake():
    start = time.time()
    refresher = make_refresher()
    try:
        metadata_path = refresher.get_metadata_path(DEMO_TABLE)
        if not metadata_path:
            raise HTTPException(404, f"No Iceberg metadata found for {FQ_TABLE} - write rows first")
        _, ok, error = refresher.refresh_table(DEMO_TABLE, metadata_path)
        if not ok:
            raise HTTPException(502, f"Snowflake refresh failed: {error}")
        return {
            "table": f"{SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}.{DEMO_TABLE.upper()}",
            "metadata_path": metadata_path,
            "seconds": round(time.time() - start, 2),
        }
    finally:
        refresher.close()


@app.get("/api/counts")
def counts():
    result = {"table": FQ_TABLE}

    start = time.time()
    try:
        rows = run_dbsql(f"SELECT COUNT(*) FROM {FQ_TABLE}")
        result["databricks"] = {"count": int(rows[0][0]), "seconds": round(time.time() - start, 2)}
    except HTTPException as exc:
        result["databricks"] = {"count": None, "error": str(exc.detail)}

    start = time.time()
    refresher = make_refresher()
    try:
        cursor = refresher.snowflake_conn.cursor()
        cursor.execute(
            f'SELECT COUNT(*) FROM {SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}."{DEMO_TABLE.upper()}"'
        )
        result["snowflake"] = {
            "count": int(cursor.fetchone()[0]),
            "seconds": round(time.time() - start, 2),
        }
    except Exception as exc:  # table absent until first refresh - that's part of the demo
        result["snowflake"] = {"count": None, "error": str(exc).splitlines()[0]}
    finally:
        refresher.close()

    return result


@app.get("/api/rbac/compare")
def rbac_compare():
    """Run the identical query through both persona catalogs."""
    out = {}
    for key, p in RBAC_PERSONAS.items():
        stmt = (
            "SELECT region, customer_name, customer_email, credit_card, amount "
            f"FROM {p['catalog']}.{RBAC_SCHEMA}.{RBAC_TABLE} ORDER BY 1, 2"
        )
        start = time.time()
        try:
            rows = run_dbsql(stmt)
            out[key] = {
                "catalog": p["catalog"],
                "role": p["role"],
                "blurb": p["blurb"],
                "rows": rows,
                "seconds": round(time.time() - start, 2),
            }
        except HTTPException as exc:
            out[key] = {"catalog": p["catalog"], "role": p["role"], "error": str(exc.detail)}
    return out


@app.get("/api/rbac/policies")
def rbac_policies():
    """Pull the live policy DDL from Snowflake - proof governance lives there."""
    import snowflake.connector

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    )
    cursor = conn.cursor()
    try:
        ddl = {}
        for policy in RBAC_POLICIES:
            cursor.execute(f"SELECT GET_DDL('POLICY', 'RBAC_DEMO.SALES.{policy}')")
            ddl[policy] = cursor.fetchone()[0]
        return ddl
    except Exception as exc:
        raise HTTPException(502, f"Snowflake policy lookup failed: {exc}")
    finally:
        cursor.close()
        conn.close()


static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")
