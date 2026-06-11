import { useEffect, useState } from "react";

type MetricResult = { title: string; columns: string[]; rows: string[][]; seconds: number };
type Summary = {
  view: string;
  queried_at: string;
  seconds: number;
  results: Record<string, MetricResult>;
};
type Info = {
  view: string;
  yaml: string | null;
  source: string | null;
  error?: string;
  links: Record<string, string>;
};

const fmtCell = (col: string, v: string) =>
  /sales|ticket/.test(col) ? `$${Number(v).toLocaleString()}` : Number(v).toLocaleString();

const LINK_LABELS: [string, string][] = [
  ["explorer", "Open in Catalog Explorer"],
  ["lineage", "Lineage"],
  ["source_explorer", "Federated source table"],
  ["genie", "Genie space"],
];

export default function MetricsPanel() {
  const [data, setData] = useState<Summary | null>(null);
  const [info, setInfo] = useState<Info | null>(null);
  const [showYaml, setShowYaml] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/metrics/info")
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
        setInfo(await res.json());
      })
      .catch((e) => setError(String(e)));
  }, []);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/metrics/summary");
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      setData(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <p className="text-slate-600">
        A Unity Catalog <strong>metric view</strong> whose source is the federated Snowflake{" "}
        <code className="rounded bg-slate-200 px-1">store_sales</code> table — governed measures
        like <code className="rounded bg-slate-200 px-1">total_sales</code> defined once in YAML,
        queried with <code className="rounded bg-slate-200 px-1">MEASURE()</code>. No app-side
        caching — the timings are real. The view declares 6-hourly materializations (relaxed
        mode), so fast answers were served from a materialized aggregate in Databricks; slow ones
        went over the wire to Snowflake.
      </p>

      {info && (
        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-[#FF3621]">
              {info.view.split(".").pop()}
            </h3>
            <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700">
              METRIC_VIEW
            </span>
            {info.links.genie && (
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                Genie data asset (tab 6)
              </span>
            )}
          </div>
          {info.source && (
            <p className="mt-2 text-xs text-slate-500">
              source: <span className="font-mono">{info.source}</span> — a foreign catalog table,
              read live from Snowflake via Lakehouse Federation
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-3">
            {LINK_LABELS.filter(([key]) => info.links[key]).map(([key, label]) => (
              <a
                key={key}
                href={info.links[key]}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                {label} ↗
              </a>
            ))}
            {info.yaml && (
              <button
                onClick={() => setShowYaml((s) => !s)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                {showYaml ? "Hide YAML definition" : "Show YAML definition"}
              </button>
            )}
          </div>
          {showYaml && info.yaml && (
            <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
              {info.yaml}
            </pre>
          )}
        </div>
      )}

      <div className="mt-6 flex gap-4">
        <button
          onClick={run}
          disabled={busy}
          className="rounded-xl bg-[#FF3621] px-6 py-3 font-semibold text-white shadow hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Querying Snowflake live…" : "Run MEASURE() queries (live, uncached)"}
        </button>
        {data && (
          <span className="self-center rounded-full bg-sky-100 px-3 py-1 text-xs font-medium text-sky-700">
            live federated query · {data.seconds}s total · at {data.queried_at}
          </span>
        )}
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {data && (
        <div className="mt-6 flex flex-col gap-6 md:flex-row">
          {Object.entries(data.results).map(([key, r]) => (
            <div
              key={key}
              className="flex-1 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {r.title}
                </h3>
                <span className="text-xs text-slate-400">{r.seconds}s</span>
              </div>
              <table className="mt-3 w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-500">
                    {r.columns.map((c) => (
                      <th key={c} className="py-1 pr-2 font-medium">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {r.rows.map((row, i) => (
                    <tr key={i} className="border-b border-slate-100">
                      {row.map((v, j) => (
                        <td key={j} className="py-1 pr-2 text-slate-700">
                          {fmtCell(r.columns[j], v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {data && (
        <p className="mt-3 text-center text-xs text-slate-400">
          Federated queries never hit the DBSQL result cache; with relaxed materialization the
          optimizer may serve from the scheduled materialized views instead — the timing tells you
          which path you got.
        </p>
      )}
    </div>
  );
}
