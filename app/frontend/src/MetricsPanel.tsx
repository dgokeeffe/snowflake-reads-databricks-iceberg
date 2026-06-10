import { useState } from "react";

type MetricResult = { title: string; columns: string[]; rows: string[][] };
type Summary = {
  view: string;
  queried_at: string;
  seconds: number;
  cached: boolean;
  results: Record<string, MetricResult>;
};

const fmtCell = (col: string, v: string) =>
  /sales|ticket/.test(col) ? `$${Number(v).toLocaleString()}` : Number(v).toLocaleString();

export default function MetricsPanel() {
  const [data, setData] = useState<Summary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (force: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/metrics/summary?force=${force}`);
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
        like <code className="rounded bg-slate-200 px-1">total_sales</code> defined once, queried
        with <code className="rounded bg-slate-200 px-1">MEASURE()</code>. Every query runs live
        against Snowflake (federation skips the result cache), so the app caches results itself.
      </p>

      <div className="mt-6 flex gap-4">
        <button
          onClick={() => run(false)}
          disabled={busy}
          className="rounded-xl bg-[#FF3621] px-6 py-3 font-semibold text-white shadow hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Querying…" : "Run MEASURE() queries"}
        </button>
        <button
          onClick={() => run(true)}
          disabled={busy}
          className="rounded-xl border border-slate-300 px-4 py-3 text-slate-600 hover:bg-white disabled:opacity-40"
        >
          Force live re-query
        </button>
        {data && (
          <span
            className={
              "self-center rounded-full px-3 py-1 text-xs font-medium " +
              (data.cached ? "bg-amber-100 text-amber-700" : "bg-sky-100 text-sky-700")
            }
          >
            {data.cached
              ? `served from app cache (queried at ${data.queried_at})`
              : `live federated query · ${data.seconds}s`}
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
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                {r.title}
              </h3>
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
        <p className="mt-3 text-center text-xs text-slate-400">{data.view}</p>
      )}
    </div>
  );
}
