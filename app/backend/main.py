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


static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")
