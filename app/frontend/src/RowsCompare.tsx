import { useCallback, useEffect, useState } from "react";

type EngineRows = { rows: string[][]; max_id: number | null; error?: string };
type RowsResponse = { columns: string[]; databricks?: EngineRows; snowflake?: EngineRows };

function RowsTable(props: {
  name: string;
  accent: string;
  columns: string[];
  data?: EngineRows;
  highlightAbove: number | null;
}) {
  const { name, accent, columns, data, highlightAbove } = props;
  return (
    <div className="flex-1 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold uppercase tracking-wide" style={{ color: accent }}>
        {name}
      </h3>
      {data?.error ? (
        <p className="mt-3 text-xs text-amber-700">{data.error}</p>
      ) : (
        <table className="mt-3 w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-slate-500">
              {columns.map((c) => (
                <th key={c} className="py-1 pr-2 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            {(data?.rows ?? []).map((row, i) => {
              const missing =
                highlightAbove !== null && Number(row[0]) > highlightAbove;
              return (
                <tr key={i} className={"border-b border-slate-100 " + (missing ? "bg-amber-50" : "")}>
                  {row.map((v, j) => (
                    <td
                      key={j}
                      className={
                        "max-w-48 truncate py-1 pr-2 " +
                        (missing ? "text-amber-700" : "text-slate-700")
                      }
                    >
                      {String(v)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function RowsCompare(props: { version: number }) {
  const [data, setData] = useState<RowsResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetch("/api/rows");
      if (res.ok) setData(await res.json());
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, props.version]);

  const dbxMax = data?.databricks?.max_id ?? null;
  const sfMax = data?.snowflake?.max_id ?? null;
  const ahead = dbxMax !== null && sfMax !== null ? dbxMax - sfMax : null;

  return (
    <div className="mt-8">
      <div className="flex items-center gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          The data itself — latest rows, newest first
        </h3>
        {busy && <span className="text-xs text-slate-400">loading…</span>}
        {!busy && ahead !== null && ahead > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
            Snowflake is {ahead.toLocaleString()} event_ids behind — amber rows not yet visible
          </span>
        )}
        {!busy && ahead === 0 && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
            identical — both engines see the same latest row
          </span>
        )}
      </div>
      {data && (
        <div className="mt-3 flex flex-col gap-6 md:flex-row">
          <RowsTable
            name="Databricks"
            accent="#FF3621"
            columns={data.columns}
            data={data.databricks}
            highlightAbove={sfMax}
          />
          <RowsTable
            name="Snowflake"
            accent="#29B5E8"
            columns={data.columns}
            data={data.snowflake}
            highlightAbove={null}
          />
        </div>
      )}
    </div>
  );
}
