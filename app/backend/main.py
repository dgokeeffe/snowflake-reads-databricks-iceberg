"""Demo Databricks App: watch Snowflake catch up to Databricks Iceberg writes.

Endpoints, by demo section:
  POST /api/write               - insert rows into a UC managed Iceberg table (Databricks)
  POST /api/refresh             - PyIceberg metadata discovery + ALTER ICEBERG TABLE REFRESH (Snowflake)
  GET  /api/counts              - row counts from both engines, side by side
  GET  /api/rows                - latest rows from both engines (the diff is the lag)
  GET  /api/federation/overview - live UC connection + foreign catalog introspection
  GET  /api/rbac/compare        - same query through two role-pinned foreign catalogs
  GET  /api/rbac/policies       - live Snowflake policy DDL via GET_DDL
  GET  /api/metrics/summary     - MEASURE() queries over the federated metric view (uncached)
  GET  /api/metrics/info        - metric view YAML, source, and Catalog Explorer links
  GET  /api/genie/info          - link-out to the Genie space on the metric view

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

# Databricks Apps injects DATABRICKS_HOST without a scheme; PyIceberg needs a full URL
_host = os.getenv("DATABRICKS_HOST", "")
if _host and not _host.startswith(("https://", "http://")):
    os.environ["DATABRICKS_HOST"] = f"https://{_host}"

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

# Federation overview: the live UC connection plus the foreign catalogs built on
# it (see setup_snowflake_m2m.py / create_tpcds_foreign_catalogs.py in the
# benchmark project). Names are introspected live; blurbs are the narrative.
FEDERATION_CONNECTION = os.getenv("FEDERATION_CONNECTION", "davidokeeffe_snowflake_conn_m2m")
FEDERATION_CATALOGS = [
    {
        "name": "davidokeeffe_tpcds_sf1_native",
        "kind": "query federation",
        "blurb": "TPC-DS sf1 in Snowflake, queried live over the M2M OAuth connection — also the source of the metric view",
    },
    {
        "name": "davidokeeffe_tpcds_sf1000_native",
        "kind": "query federation",
        "blurb": "TPC-DS sf1000 (1 TB) over the same connection",
    },
    {
        "name": "davidokeeffe_tpcds_sf1_horizon_stock",
        "kind": "catalog federation",
        "blurb": "Snowflake Horizon catalog federation — stock Snowflake-managed Iceberg tables",
    },
    {
        "name": "davidokeeffe_tpcds_sf1_horizon_compatible",
        "kind": "catalog federation",
        "blurb": "Horizon catalog federation — parameter-compatible Iceberg tables",
    },
    {
        "name": "davidokeeffe_tpcds_sf1_databricks",
        "kind": "catalog federation",
        "blurb": "Databricks-written Iceberg read back through Horizon catalog federation",
    },
    {
        "name": "rbac_demo_global",
        "kind": "rbac persona",
        "blurb": "Connection pinned to ANALYST_GLOBAL — all rows, PII clear",
    },
    {
        "name": "rbac_demo_au",
        "kind": "rbac persona",
        "blurb": "Connection pinned to ANALYST_AU — row access + masking policies apply",
    },
]

# Metric view over query federation: every MEASURE() query is a live federated
# query (federation never hits the DBSQL result cache). Deliberately NOT cached
# app-side — showing real federated latency on every click is part of the demo.
METRIC_VIEW = os.getenv(
    "METRIC_VIEW", "davidokeeffe_standard_demo_catalog.default.snowflake_sales_metrics"
)
METRIC_QUERIES = {
    "sales_by_store": {
        "title": "Total sales and order count by store",
        "columns": ["store_key", "total_sales", "order_count"],
        "sql": (
            "SELECT store_key, MEASURE(total_sales) AS total_sales, "
            "MEASURE(order_count) AS order_count "
            f"FROM {METRIC_VIEW} GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
        ),
    },
    "top_items_by_avg_ticket": {
        "title": "Top 5 items by average ticket",
        "columns": ["item_key", "avg_ticket", "total_quantity"],
        "sql": (
            "SELECT item_key, ROUND(MEASURE(avg_ticket), 2) AS avg_ticket, "
            "MEASURE(total_quantity) AS total_quantity "
            f"FROM {METRIC_VIEW} GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
        ),
    },
}

GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "")

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
    # event_id continues from the current max so the Snowflake-side diff is visible
    run_dbsql(
        f"INSERT INTO {FQ_TABLE} "
        f"SELECT id + (SELECT COALESCE(MAX(event_id), -1) + 1 FROM {FQ_TABLE}), "
        f"current_timestamp(), uuid() FROM range({rows})"
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


@app.get("/api/rows")
def latest_rows(limit: int = 8):
    """Latest rows from both engines, newest first — the diff IS the refresh lag."""
    limit = max(1, min(limit, 50))
    out = {"columns": ["event_id", "event_ts", "payload"]}

    try:
        rows = run_dbsql(
            f"SELECT event_id, event_ts, payload FROM {FQ_TABLE} "
            f"ORDER BY event_id DESC LIMIT {limit}"
        )
        out["databricks"] = {"rows": rows, "max_id": int(rows[0][0]) if rows else None}
    except HTTPException as exc:
        out["databricks"] = {"rows": [], "max_id": None, "error": str(exc.detail)}

    refresher = make_refresher()
    try:
        cursor = refresher.snowflake_conn.cursor()
        cursor.execute(
            f'SELECT event_id, event_ts, payload FROM {SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}."{DEMO_TABLE.upper()}" '
            f"ORDER BY event_id DESC LIMIT {limit}"
        )
        rows = [[str(c) for c in row] for row in cursor.fetchall()]
        out["snowflake"] = {"rows": rows, "max_id": int(rows[0][0]) if rows else None}
    except Exception as exc:  # table absent until first refresh
        out["snowflake"] = {"rows": [], "max_id": None, "error": str(exc).splitlines()[0]}
    finally:
        refresher.close()

    return out


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


_federation_cache: dict | None = None


@app.get("/api/federation/overview")
def federation_overview(force: bool = False):
    """Live UC introspection of the connection + foreign catalogs — proof it's real wiring."""
    global _federation_cache
    if _federation_cache is not None and not force:
        return _federation_cache

    start = time.time()
    try:
        c = workspace().connections.get(FEDERATION_CONNECTION)
        options = c.options or {}
        connection = {
            "name": c.name,
            "connection_type": c.connection_type.value if c.connection_type else None,
            "credential_type": c.credential_type.value if c.credential_type else None,
            "host": options.get("host"),
            "warehouse": options.get("sfWarehouse"),
            "comment": c.comment,
        }
    except Exception as exc:
        connection = {"name": FEDERATION_CONNECTION, "error": str(exc).splitlines()[0]}

    try:
        existing = {cat.name for cat in workspace().catalogs.list()}
    except Exception:
        existing = set()
    catalogs = [{**c, "exists": c["name"] in existing} for c in FEDERATION_CATALOGS]

    _federation_cache = {
        "connection": connection,
        "catalogs": catalogs,
        "seconds": round(time.time() - start, 2),
    }
    return _federation_cache


@app.get("/api/metrics/summary")
def metrics_summary():
    """Run the canned MEASURE() queries. Deliberately uncached — every call is a live
    federated query against Snowflake, so the audience sees real performance."""
    start = time.time()
    results = {}
    for key, q in METRIC_QUERIES.items():
        q_start = time.time()
        rows = run_dbsql(q["sql"])
        results[key] = {
            "title": q["title"],
            "columns": q["columns"],
            "rows": rows,
            "seconds": round(time.time() - q_start, 2),
        }
    return {
        "view": METRIC_VIEW,
        "queried_at": time.strftime("%H:%M:%S"),
        "seconds": round(time.time() - start, 2),
        "results": results,
    }


@app.get("/api/metrics/info")
def metrics_info():
    """What the metric view IS: its YAML definition, federated source, and link-outs."""
    host = workspace().config.host.rstrip("/")
    catalog, schema, view = METRIC_VIEW.split(".")
    info = {"view": METRIC_VIEW, "yaml": None, "source": None}
    try:
        t = workspace().tables.get(METRIC_VIEW)
        info["yaml"] = t.view_definition
        info["source"] = (t.properties or {}).get("metric_view.from.name")
    except Exception as exc:
        info["error"] = str(exc).splitlines()[0]

    links = {
        "explorer": f"{host}/explore/data/{catalog}/{schema}/{view}",
        "lineage": f"{host}/explore/data/{catalog}/{schema}/{view}?activeTab=lineage",
    }
    if info["source"]:
        links["source_explorer"] = f"{host}/explore/data/{info['source'].replace('.', '/')}"
    if GENIE_SPACE_ID:
        links["genie"] = f"{host}/genie/rooms/{GENIE_SPACE_ID}"
    info["links"] = links
    return info


@app.get("/api/genie/info")
def genie_info():
    if not GENIE_SPACE_ID:
        return {"configured": False, "space_id": None, "url": None, "view": METRIC_VIEW}
    host = workspace().config.host.rstrip("/")
    return {
        "configured": True,
        "space_id": GENIE_SPACE_ID,
        "url": f"{host}/genie/rooms/{GENIE_SPACE_ID}",
        "view": METRIC_VIEW,
    }


static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")
