"""Create the Genie space for tab 6 — data asset = the metric view.

Self-contained (no helper libs): builds the serialized_space payload inline and
POSTs to the Genie Spaces API. Prints the space ID — put it in app.yaml as
GENIE_SPACE_ID and redeploy.

    export DATABRICKS_HOST=https://adb-....azuredatabricks.net
    export DATABRICKS_AUTH_TYPE=azure-cli   # or any SDK auth
    export DATABRICKS_WAREHOUSE_ID=<warehouse id>
    uv run python deploy/create_genie_space.py
"""

from __future__ import annotations

import json
import os
import uuid

from databricks.sdk import WorkspaceClient

WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
METRIC_VIEW = os.getenv(
    "METRIC_VIEW", "davidokeeffe_standard_demo_catalog.default.snowflake_sales_metrics"
)
TITLE = os.getenv("GENIE_TITLE", "Snowflake sales — ask anything")
DESCRIPTION = (
    "Natural-language analytics over a Unity Catalog metric view whose source is a "
    "federated Snowflake TPC-DS store_sales table (Lakehouse Federation, Entra M2M OAuth)."
)
INSTRUCTIONS = (
    "Always answer from the snowflake_sales_metrics metric view using its certified measures "
    "(total_sales, total_quantity, order_count, avg_ticket) with MEASURE(). Dimensions are "
    "store_key, item_key and sold_date_key (TPC-DS surrogate keys). Mention that every query "
    "runs live against Snowflake through Lakehouse Federation."
)
SAMPLE_QUESTIONS = [
    "What are the total sales by store?",
    "What is the average ticket for the top 5 items?",
    "Which store sold the most units?",
]


def _id() -> str:
    return uuid.uuid4().hex


example_sqls = sorted(
    [
        {
            "id": _id(),
            "title": ["Total sales by store"],
            "sql": [
                f"SELECT store_key, MEASURE(total_sales) AS total_sales "
                f"FROM {METRIC_VIEW} GROUP BY 1 ORDER BY 2 DESC"
            ],
        },
        {
            "id": _id(),
            "title": ["Top 5 items by average ticket"],
            "sql": [
                f"SELECT item_key, MEASURE(avg_ticket) AS avg_ticket "
                f"FROM {METRIC_VIEW} GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
            ],
        },
    ],
    key=lambda e: e["id"],  # API requires example_question_sqls sorted by id
)

serialized_space = {
    "version": 2,
    "data_sources": {"tables": [{"identifier": METRIC_VIEW}]},
    "instructions": {
        "text_instructions": [{"id": _id(), "content": [INSTRUCTIONS]}],
        "example_question_sqls": example_sqls,
    },
    "config": {
        "sample_questions": [{"id": _id(), "question": [q]} for q in SAMPLE_QUESTIONS]
    },
}

w = WorkspaceClient()
me = w.current_user.me().user_name
parent = f"/Workspace/Users/{me}/genie"
w.workspace.mkdirs(parent)

created = w.api_client.do(
    "POST",
    "/api/2.0/genie/spaces",
    body={
        "title": TITLE,
        "description": DESCRIPTION,
        "parent_path": parent,
        "warehouse_id": WAREHOUSE_ID,
        "serialized_space": json.dumps(serialized_space),
    },
)
space_id = created.get("space_id") or created.get("id")

# Round-trip verify
back = w.api_client.do(
    "GET", f"/api/2.0/genie/spaces/{space_id}", query={"include_serialized_space": "true"}
)
inner = json.loads(back["serialized_space"])
assert any(
    t.get("identifier") == METRIC_VIEW for t in inner["data_sources"]["tables"]
), "metric view not attached"

print(f"space_id: {space_id}")
print(f"url: {w.config.host.rstrip('/')}/genie/rooms/{space_id}")
print("--> set GENIE_SPACE_ID in app.yaml and redeploy")
