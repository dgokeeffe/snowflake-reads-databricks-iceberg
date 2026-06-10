import chartUrl from "./assets/tpcds_path_comparison.png";

// Headline numbers from docs/SNOWFLAKE_QUERY_FEDERATION_PERFORMANCE.md in the
// benchmark project (99 TPC-DS queries, Azure Australia East, 2026-06-10).
const ROWS: [string, string, string][] = [
  ["Databricks native — UC Iceberg (DBSQL)", "0.59–1.11 s", "3.17 s cold"],
  ["Snowflake native", "0.86 s", "1.98 s cold (LARGE)"],
  ["Snowflake reads Databricks Iceberg (external volume)", "1.1–1.3 s", "—"],
  ["Lakehouse Federation — query federation (DBSQL)", "5.22 s (p90 11 s)", "8.5 s · 6.42 s LARGE remote"],
  ["Catalog federation — Snowflake Horizon (classic)", "7.7 s (max 20.2 s)", "—"],
];

export default function BenchmarkPanel() {
  return (
    <div>
      <p className="text-slate-600">
        The same 99 TPC-DS queries down every access path. Sharing storage is near-native;
        engine-to-engine federation costs a translation-and-transfer premium — fine for
        governance and exploration, not for dashboards.
      </p>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <img
          src={chartUrl}
          alt="TPC-DS access path comparison: sf1 and sf1000 median query durations with p90 markers"
          className="w-full rounded-lg"
        />
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Median per query
        </h3>
        <table className="mt-3 w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              <th className="py-1 pr-2 font-medium">access path</th>
              <th className="py-1 pr-2 font-medium">sf1 (1 GB)</th>
              <th className="py-1 pr-2 font-medium">sf1000 (1 TB)</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([path, sf1, sf1000]) => (
              <tr key={path} className="border-b border-slate-100">
                <td className="py-1.5 pr-2 text-slate-700">{path}</td>
                <td className="py-1.5 pr-2 font-mono text-slate-700">{sf1}</td>
                <td className="py-1.5 pr-2 font-mono text-slate-700">{sf1000}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="mt-4 space-y-1 text-xs text-slate-500">
          <li>
            · Federated queries never hit the DBSQL result or disk cache — warm ≈ cold. (That's
            why the next tab caches app-side.)
          </li>
          <li>
            · The federation long tail comes from queries that don't push down — Snowflake ships
            raw rows and DBSQL finishes the join.
          </li>
        </ul>
      </div>
    </div>
  );
}
