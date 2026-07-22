import { useEffect, useState } from "react";
import { fetchCaseDetail, fetchCases, runBoard } from "./api";
import { PatientList } from "./components/PatientList";
import { PatientChart } from "./components/PatientChart";
import { FindingsPanel } from "./components/FindingsPanel";
import { ActionLedger } from "./components/ActionLedger";
import { PanelDeliberation } from "./components/PanelDeliberation";
import type { CaseDetail, CaseSummary, PanelResult } from "./types";

type View = "chart" | "analysis";

export default function App() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [view, setView] = useState<View>("chart");
  const [results, setResults] = useState<Record<string, PanelResult>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCases()
      .then((cs) => {
        setCases(cs);
        if (cs.length) setSelected(cs[0].case_id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    fetchCaseDetail(selected)
      .then(setDetail)
      .catch((e) => setError(String(e)));
  }, [selected]);

  async function convene() {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const r = await runBoard(selected);
      setResults((prev) => ({ ...prev, [selected]: r })); // remembered per patient
      setView("analysis");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  // Analysis is viewed per patient — show the selected patient's result (or none yet).
  const result = selected ? results[selected] : undefined;

  return (
    <div className="app">
      <header className="app__head">
        <div>
          <h1>Tumor Board — Multi-Specialist Panel</h1>
          <p className="app__tag">A panel of specialists reviews each case and surfaces the gaps the room missed.</p>
        </div>
        <div className="app__actions">
          <div className="viewswitch">
            <button className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>
              Patient chart
            </button>
            <button className={view === "analysis" ? "on" : ""} onClick={() => setView("analysis")}>
              Panel findings
            </button>
          </div>
          <button className="run" onClick={convene} disabled={loading}>
            {loading ? "Convening…" : "Convene board"}
          </button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="layout">
        <PatientList cases={cases} selected={selected} onSelect={setSelected} />

        {view === "chart" ? (
          detail ? (
            <PatientChart detail={detail} />
          ) : (
            <section className="chart">
              <p className="empty">{selected ? "Loading chart…" : "Select a patient."}</p>
            </section>
          )
        ) : (
          <section className="chart">
            <div className="findings-col">
              {loading && (
                <div className="warn">
                  Convening the panel — the router picks specialists, they review in parallel, then
                  cross-examine any disagreement. This runs several model calls and takes a bit.
                </div>
              )}
              {result?.truncated && (
                <div className="warn">
                  Some model output was truncated — this run may be incomplete, not empty.
                </div>
              )}
              {!result && !loading && (
                <p className="empty">
                  No analysis yet. Click <code>Convene board</code> to run the specialist panel over the
                  selected patient.
                </p>
              )}
              {result && <PanelDeliberation result={result} />}
              <FindingsPanel findings={result?.findings ?? []} />
              <ActionLedger items={result?.action_ledger ?? []} />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
