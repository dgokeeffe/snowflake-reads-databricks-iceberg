"""Grant the app's service principal everything the six demo sections need.

Run as a user who owns (or can grant on) the catalogs below. EXTERNAL USE SCHEMA
may require metastore admin. Idempotent — grants are additive.

    export DATABRICKS_HOST=https://adb-....azuredatabricks.net
    export DATABRICKS_AUTH_TYPE=azure-cli   # or any SDK auth
    uv run python deploy/grant_app_sp.py
"""

from __future__ import annotations

import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

APP_NAME = os.getenv("APP_NAME", "iceberg-refresh-demo")
WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
DEMO_CATALOG = os.getenv("DEMO_CATALOG", "davidokeeffe_standard_demo_catalog")
DEMO_SCHEMA = os.getenv("DEMO_SCHEMA", "iceberg_demo")
METRIC_VIEW = os.getenv(
    "METRIC_VIEW", f"{DEMO_CATALOG}.default.snowflake_sales_metrics"
)
METRIC_SOURCE_CATALOG = os.getenv("METRIC_SOURCE_CATALOG", "davidokeeffe_tpcds_sf1_native")
RBAC_CATALOGS = [
    os.getenv("RBAC_CATALOG_GLOBAL", "rbac_demo_global"),
    os.getenv("RBAC_CATALOG_AU", "rbac_demo_au"),
]
FEDERATION_CONNECTION = os.getenv("FEDERATION_CONNECTION", "davidokeeffe_snowflake_conn_m2m")
# Display-only catalogs on the federation-overview tab (visibility, no data access)
DISPLAY_CATALOGS = os.getenv(
    "DISPLAY_CATALOGS",
    "davidokeeffe_tpcds_sf1000_native,davidokeeffe_tpcds_sf1_horizon_stock,"
    "davidokeeffe_tpcds_sf1_horizon_compatible,davidokeeffe_tpcds_sf1_databricks",
).split(",")

w = WorkspaceClient()
sp = w.apps.get(APP_NAME).service_principal_client_id
print(f"app SP: {sp}")

mv_catalog, mv_schema, _ = METRIC_VIEW.split(".")


def sql(stmt: str) -> None:
    r = w.statement_execution.execute_statement(
        statement=stmt, warehouse_id=WAREHOUSE_ID, wait_timeout="50s"
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error}")


GRANTS = [
    # Tab 1 write path — schema must exist before EXTERNAL USE SCHEMA can be granted
    f"CREATE SCHEMA IF NOT EXISTS {DEMO_CATALOG}.{DEMO_SCHEMA}",
    f"GRANT USE CATALOG, CREATE SCHEMA ON CATALOG {DEMO_CATALOG} TO `{sp}`",
    f"GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA {DEMO_CATALOG}.{DEMO_SCHEMA} TO `{sp}`",
    # PyIceberg reads table metadata via the UC Iceberg REST API — without this,
    # /api/refresh 403s (not covered by ALL PRIVILEGES; may need metastore admin)
    f"GRANT EXTERNAL USE SCHEMA ON SCHEMA {DEMO_CATALOG}.{DEMO_SCHEMA} TO `{sp}`",
    # Tab 5 metric view + its federated source
    f"GRANT USE SCHEMA ON SCHEMA {mv_catalog}.{mv_schema} TO `{sp}`",
    f"GRANT SELECT ON TABLE {METRIC_VIEW} TO `{sp}`",
    f"GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG {METRIC_SOURCE_CATALOG} TO `{sp}`",
    # Tab 3 RBAC persona catalogs
    *[f"GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG {c} TO `{sp}`" for c in RBAC_CATALOGS],
    # Tab 2 federation overview (optional — the tab degrades gracefully without)
    f"GRANT USE CONNECTION ON CONNECTION {FEDERATION_CONNECTION} TO `{sp}`",
    *[f"GRANT USE CATALOG ON CATALOG {c.strip()} TO `{sp}`" for c in DISPLAY_CATALOGS if c.strip()],
]

failures = 0
for stmt in GRANTS:
    try:
        sql(stmt)
        print("OK  ", stmt[:110])
    except Exception as exc:
        failures += 1
        print("FAIL", stmt[:110], "->", str(exc)[:160])
print(f"done, {failures} failure(s)")
