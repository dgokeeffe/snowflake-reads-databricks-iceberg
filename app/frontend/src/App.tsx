import { useCallback, useEffect, useState } from "react";
import RbacPanel from "./RbacPanel";
import FederationPanel from "./FederationPanel";
import BenchmarkPanel from "./BenchmarkPanel";
import MetricsPanel from "./MetricsPanel";
import GeniePanel from "./GeniePanel";
import RowsCompare from "./RowsCompare";
import architectureDiagram from "./assets/architecture-network.png";

type EngineCount = { count: number | null; seconds?: number; error?: string };
type Counts = { table: string; databricks?: EngineCount; snowflake?: EngineCount };
type LogLine = { ts: string; text: string; kind: "info" | "ok" | "err" };

const fmt = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n.toLocaleString();

async function post(path: string, body?: object) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail ?? res.statusText);
  return data;
}

function EngineCard(props: { name: string; accent: string; data?: EngineCount; stale: boolean }) {
  const { name, accent, data, stale } = props;
  return (
    <div className="flex-1 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide" style={{ color: accent }}>
          {name}
        </h2>
        {stale && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            behind — refresh needed
          </span>
        )}
      </div>
      <p className="mt-3 text-5xl font-bold tabular-nums text-slate-900">{fmt(data?.count)}</p>
      <p className="mt-2 text-xs text-slate-500">
        {data?.error
          ? data.error
          : data?.seconds !== undefined
            ? `rows · queried in ${data.seconds}s`
            : "rows"}
      </p>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<
    "refresh" | "federation" | "rbac" | "benchmarks" | "metrics" | "genie"
  >("refresh");
  const [counts, setCounts] = useState<Counts | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [dataVersion, setDataVersion] = useState(0);

  const addLog = (text: string, kind: LogLine["kind"] = "info") =>
    setLog((l) => [{ ts: new Date().toLocaleTimeString(), text, kind }, ...l].slice(0, 30));

  const loadCounts = useCallback(async () => {
    const data: Counts = await (await fetch("/api/counts")).json();
    setCounts(data);
    setDataVersion((v) => v + 1);
    return data;
  }, []);

  useEffect(() => {
    loadCounts().catch(() => addLog("Could not load counts", "err"));
  }, [loadCounts]);

  const doWrite = async () => {
    setBusy("write");
    try {
      const r = await post("/api/write", { rows: 1000 });
      addLog(`Databricks: inserted ${fmt(r.inserted)} rows into ${r.table} (${r.seconds}s)`, "ok");
      await loadCounts();
    } catch (e) {
      addLog(`Write failed: ${e}`, "err");
    } finally {
      setBusy(null);
    }
  };

  const doRefresh = async () => {
    setBusy("refresh");
    try {
      const r = await post("/api/refresh");
      addLog(`Snowflake: re-pointed ${r.table} at ${r.metadata_path} (${r.seconds}s)`, "ok");
      await loadCounts();
    } catch (e) {
      addLog(`Refresh failed: ${e}`, "err");
    } finally {
      setBusy(null);
    }
  };

  const stale =
    counts?.databricks?.count != null &&
    counts.databricks.count !== (counts.snowflake?.count ?? null);

  return (
    <div className="min-h-screen bg-stone-50 px-6 py-10">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-3xl font-bold text-slate-900">
          Snowflake reads Databricks Iceberg
        </h1>
        <div className="mt-4 flex flex-wrap gap-1 rounded-xl bg-slate-200 p-1 w-fit">
          {(
            [
              ["refresh", "1 · Iceberg refresh"],
              ["federation", "2 · Federation setup"],
              ["rbac", "3 · RBAC personas"],
              ["benchmarks", "4 · Benchmarks"],
              ["metrics", "5 · Metric view"],
              ["genie", "6 · Genie"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={
                "rounded-lg px-4 py-2 text-sm font-medium " +
                (tab === key ? "bg-white text-slate-900 shadow" : "text-slate-600")
              }
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "federation" && (
          <div className="mt-6">
            <FederationPanel />
          </div>
        )}

        {tab === "rbac" && (
          <div className="mt-6">
            <RbacPanel />
          </div>
        )}

        {tab === "benchmarks" && (
          <div className="mt-6">
            <BenchmarkPanel />
          </div>
        )}

        {tab === "metrics" && (
          <div className="mt-6">
            <MetricsPanel />
          </div>
        )}

        {tab === "genie" && (
          <div className="mt-6">
            <GeniePanel />
          </div>
        )}

        {tab === "refresh" && (
          <>
        <p className="mt-6 text-slate-600">
          One copy of data on Azure storage. Write in Databricks, then re-point Snowflake at the
          new <code className="rounded bg-slate-200 px-1">metadata.json</code> — and watch it
          catch up.
        </p>

        <div className="mt-8 flex gap-4">
          <button
            onClick={doWrite}
            disabled={busy !== null}
            className="rounded-xl bg-[#FF3621] px-6 py-3 font-semibold text-white shadow hover:opacity-90 disabled:opacity-40"
          >
            {busy === "write" ? "Writing…" : "1 · Write 1,000 rows (Databricks)"}
          </button>
          <button
            onClick={doRefresh}
            disabled={busy !== null}
            className="rounded-xl bg-[#29B5E8] px-6 py-3 font-semibold text-white shadow hover:opacity-90 disabled:opacity-40"
          >
            {busy === "refresh" ? "Refreshing…" : "2 · Refresh Snowflake"}
          </button>
          <button
            onClick={() => loadCounts()}
            disabled={busy !== null}
            className="rounded-xl border border-slate-300 px-4 py-3 text-slate-600 hover:bg-white"
          >
            Re-query
          </button>
        </div>

        <div className="mt-8 flex gap-6">
          <EngineCard name="Databricks" accent="#FF3621" data={counts?.databricks} stale={false} />
          <EngineCard
            name="Snowflake"
            accent="#29B5E8"
            data={counts?.snowflake}
            stale={Boolean(stale)}
          />
        </div>

        <p className="mt-3 text-center text-xs text-slate-400">
          {counts?.table ?? ""} · Snowflake reads the same parquet files directly from ADLS via an
          External Volume — no Snowflake→Databricks connection
        </p>

        <RowsCompare version={dataVersion} />

        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Recommended flow — one copy of data, no engine-to-engine connection
          </h3>
          <img
            src={architectureDiagram}
            alt="Network architecture: Python Iceberg client discovers metadata via the UC Iceberg REST API, then ALTER ICEBERG TABLE REFRESH re-points Snowflake's External Volume at the new metadata.json on ADLS — no Snowflake-to-Databricks connection"
            className="mt-3 w-full rounded-lg"
          />
        </div>

        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Activity
          </h3>
          <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto font-mono text-xs">
            {log.length === 0 && <li className="text-slate-400">No activity yet.</li>}
            {log.map((l, i) => (
              <li
                key={i}
                className={
                  l.kind === "err"
                    ? "text-red-600"
                    : l.kind === "ok"
                      ? "text-emerald-700"
                      : "text-slate-600"
                }
              >
                [{l.ts}] {l.text}
              </li>
            ))}
          </ul>
        </div>
          </>
        )}
      </div>
    </div>
  );
}
