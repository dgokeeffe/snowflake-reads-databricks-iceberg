import { useEffect, useState } from "react";

type GenieInfo = {
  configured: boolean;
  space_id: string | null;
  url: string | null;
  view: string;
};

const SAMPLE_QUESTIONS = [
  "What are the total sales by store?",
  "What's the average ticket for the top 5 items?",
  "Which store sold the most units?",
];

export default function GeniePanel() {
  const [info, setInfo] = useState<GenieInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/genie/info")
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
        setInfo(await res.json());
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <p className="text-slate-600">
        The last step of the ladder: a <strong>Genie</strong> space on top of the metric view.
        Business users ask questions in plain English; Genie answers using the view's certified
        measures — and underneath, every answer is a live federated query against Snowflake.
      </p>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[#FF3621]">
          Try asking
        </h3>
        <ul className="mt-3 space-y-2">
          {SAMPLE_QUESTIONS.map((q) => (
            <li key={q} className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">
              “{q}”
            </li>
          ))}
        </ul>

        {info?.configured && info.url ? (
          <a
            href={info.url}
            target="_blank"
            rel="noreferrer"
            className="mt-6 inline-block rounded-xl bg-[#FF3621] px-6 py-3 font-semibold text-white shadow hover:opacity-90"
          >
            Open the Genie space ↗
          </a>
        ) : (
          <p className="mt-6 text-xs text-amber-700">
            Genie space not configured yet — set GENIE_SPACE_ID in app.yaml.
          </p>
        )}

        {info && (
          <p className="mt-3 text-xs text-slate-400">
            Data asset: <span className="font-mono">{info.view}</span>
            {info.space_id && (
              <>
                {" · space "}
                <span className="font-mono">{info.space_id}</span>
              </>
            )}
          </p>
        )}
      </div>

      <p className="mt-3 text-center text-xs text-slate-400">
        Genie opens in a new tab — embedding Genie inside an app iframe isn't supported.
      </p>
    </div>
  );
}
