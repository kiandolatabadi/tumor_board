import { useEffect, useState } from "react";
import { fetchCaseDetail, fetchCases, runAnalysis } from "./api";
import { PatientList } from "./components/PatientList";
import { PatientChart } from "./components/PatientChart";
import { FindingsPanel } from "./components/FindingsPanel";
import { ActionLedger } from "./components/ActionLedger";
import { InferredPanel } from "./components/InferredPanel";
import type { AnalysisResult, CaseDetail, CaseSummary } from "./types";

type View = "chart" | "analysis";

export default function App() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [view, setView] = useState<View>("chart");
  const [results, setResults] = useState<Record<string, AnalysisResult>>({});
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

  async function analyze() {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const r = await runAnalysis(selected);
      setResults((prev) => ({ ...prev, [selected]: r }));  // remembered per patient
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
        <h1>Tumor Board — Gap Detection</h1>
        <div className="app__actions">
          <div className="viewswitch">
            <button className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>
              Patient chart
            </button>
            <button className={view === "analysis" ? "on" : ""} onClick={() => setView("analysis")}>
              Analysis
            </button>
          </div>
          <button className="run" onClick={analyze} disabled={loading}>
            {loading ? "Analyzing…" : "Run analysis"}
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
              {result?.truncated && (
                <div className="warn">
                  Output was truncated — only complete findings were recovered. This run is
                  incomplete, not empty.
                </div>
              )}
              {!result && (
                <p className="empty">
                  No analysis yet. Click <code>Run analysis</code> to analyze the selected
                  patient — this runs the full pipeline and takes a bit.
                </p>
              )}
              <FindingsPanel findings={result?.findings ?? []} />
              {result?.enrichment && <InferredPanel enrichment={result.enrichment} />}
              <ActionLedger items={result?.action_ledger ?? []} />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
