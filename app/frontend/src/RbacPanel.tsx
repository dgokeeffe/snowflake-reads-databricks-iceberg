import { useState } from "react";

type PersonaResult = {
  catalog: string;
  role: string;
  blurb?: string;
  rows?: string[][];
  seconds?: number;
  error?: string;
};
type CompareResponse = Record<"global" | "au", PersonaResult>;

const HEADERS = ["region", "customer", "email", "card", "amount"];
const isMasked = (v: string) => typeof v === "string" && v.includes("*");

function PersonaTable(props: { title: string; accent: string; data?: PersonaResult }) {
  const { title, accent, data } = props;
  return (
    <div className="flex-1 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold uppercase tracking-wide" style={{ color: accent }}>
        {title}
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        {data ? `${data.role} · catalog ${data.catalog}` : "…"}
        {data?.blurb ? ` — ${data.blurb}` : ""}
      </p>
      {data?.error ? (
        <p className="mt-3 text-xs text-red-600">{data.error}</p>
      ) : (
        <table className="mt-3 w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              {HEADERS.map((h) => (
                <th key={h} className="py-1 pr-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            {(data?.rows ?? []).map((row, i) => (
              <tr key={i} className="border-b border-slate-100">
                {row.map((v, j) => (
                  <td
                    key={j}
                    className={
                      "py-1 pr-2 " +
                      (isMasked(String(v)) ? "bg-amber-50 text-amber-700" : "text-slate-700")
                    }
                  >
                    {String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-right text-xs text-slate-400">
        {data?.rows ? `${data.rows.length} row(s)` : ""}
        {data?.seconds !== undefined ? ` · ${data.seconds}s` : ""}
      </p>
    </div>
  );
}

export default function RbacPanel() {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [policies, setPolicies] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const compare = async () => {
    setBusy("compare");
    setError(null);
    try {
      const res = await fetch("/api/rbac/compare");
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      setData(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const loadPolicies = async () => {
    setBusy("policies");
    setError(null);
    try {
      const res = await fetch("/api/rbac/policies");
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      setPolicies(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <p className="text-slate-600">
        The same Snowflake table, queried twice from this workspace's SQL warehouse through two
        foreign catalogs — each backed by a connection pinned to a different Snowflake role.
        Snowflake's row access and masking policies do the rest.
      </p>

      <div className="mt-6 flex gap-4">
        <button
          onClick={compare}
          disabled={busy !== null}
          className="rounded-xl bg-[#29B5E8] px-6 py-3 font-semibold text-white shadow hover:opacity-90 disabled:opacity-40"
        >
          {busy === "compare" ? "Querying…" : "Run the same query as both personas"}
        </button>
        <button
          onClick={loadPolicies}
          disabled={busy !== null}
          className="rounded-xl border border-slate-300 px-4 py-3 text-slate-600 hover:bg-white"
        >
          {busy === "policies" ? "Loading…" : "Show the Snowflake policy DDL"}
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {data && (
        <div className="mt-6 flex gap-6">
          <PersonaTable title="Global analyst" accent="#16A34A" data={data.global} />
          <PersonaTable title="AU analyst" accent="#D97706" data={data.au} />
        </div>
      )}

      {data && (
        <p className="mt-3 text-center text-xs text-slate-400">
          Amber cells were masked by Snowflake before they ever reached Databricks.
        </p>
      )}

      {policies && (
        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Live policy DDL (from Snowflake, via GET_DDL)
          </h3>
          {Object.entries(policies).map(([name, ddl]) => (
            <pre
              key={name}
              className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100"
            >
              {ddl}
            </pre>
          ))}
        </div>
      )}
    </div>
  );
}
