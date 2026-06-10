import { useEffect, useState } from "react";

type Connection = {
  name: string;
  connection_type?: string | null;
  credential_type?: string | null;
  host?: string | null;
  warehouse?: string | null;
  comment?: string | null;
  error?: string;
};
type Catalog = { name: string; kind: string; blurb: string; exists: boolean };
type Overview = { connection: Connection; catalogs: Catalog[]; seconds: number };

const KIND_STYLES: Record<string, string> = {
  "query federation": "bg-sky-100 text-sky-700",
  "catalog federation": "bg-violet-100 text-violet-700",
  "rbac persona": "bg-emerald-100 text-emerald-700",
};

export default function FederationPanel() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/federation/overview")
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
        setData(await res.json());
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <p className="text-slate-600">
        How the Databricks side is wired: one Unity Catalog connection to Snowflake (Entra ID
        M2M OAuth — no passwords), and the foreign catalogs built on top of it. Everything below
        is introspected live from Unity Catalog, not hardcoded slideware.
      </p>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {data && (
        <>
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-[#FF3621]">
              UC connection
            </h3>
            {data.connection.error ? (
              <p className="mt-2 text-xs text-amber-700">
                {data.connection.name}: {data.connection.error}
              </p>
            ) : (
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
                {(
                  [
                    ["Name", data.connection.name],
                    ["Type", data.connection.connection_type],
                    ["Auth", data.connection.credential_type ?? "OAuth M2M"],
                    ["Remote warehouse", data.connection.warehouse],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs text-slate-400">{k}</dt>
                    <dd className="font-mono text-xs text-slate-700">{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
            )}
            {data.connection.comment && (
              <p className="mt-3 text-xs text-slate-500">{data.connection.comment}</p>
            )}
          </div>

          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Foreign catalogs on this workspace
            </h3>
            <table className="mt-3 w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-1 pr-2 font-medium">catalog</th>
                  <th className="py-1 pr-2 font-medium">kind</th>
                  <th className="py-1 pr-2 font-medium">what it demonstrates</th>
                </tr>
              </thead>
              <tbody>
                {data.catalogs.map((c) => (
                  <tr key={c.name} className="border-b border-slate-100">
                    <td className="py-1.5 pr-2 font-mono text-slate-700">
                      {c.name}
                      {!c.exists && <span className="ml-1 text-red-500">(missing!)</span>}
                    </td>
                    <td className="py-1.5 pr-2">
                      <span
                        className={
                          "rounded-full px-2 py-0.5 text-xs font-medium " +
                          (KIND_STYLES[c.kind] ?? "bg-slate-100 text-slate-600")
                        }
                      >
                        {c.kind}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-slate-600">{c.blurb}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-center text-xs text-slate-400">
            Connection and catalog list fetched live from Unity Catalog in {data.seconds}s.
          </p>
        </>
      )}
    </div>
  );
}
