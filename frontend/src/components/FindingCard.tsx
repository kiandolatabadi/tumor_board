import type { Finding } from "../types";

// Scannable scaffold: each finding collapses to a one-line summary (issue + the
// key badges) so the whole list reads at a glance, and expands to the full detail
// (recommendation, patient note, live question, evidence) on click. Native
// <details>/<summary> — accessible, no extra state.
export function FindingCard({ f, index }: { f: Finding; index: number }) {
  const notConfirmed = f.operability_status === "not_confirmed";
  return (
    <details className={`finding ${notConfirmed ? "finding--warn" : ""}`}>
      <summary className="finding__summary">
        <span className="finding__num">{index}</span>
        <span className="finding__issue">{f.issue}</span>
        <span className="finding__badges">
          {f.recommendation_grade && (
            <span className="badge badge--grade" title="Class of Recommendation / Level of Evidence">
              {f.recommendation_grade}
            </span>
          )}
          {/* Operability is a code-enforced safety gate — always show its verdict on a
              procedure-proposing finding, cleared or not. */}
          {f.operability_status === "not_confirmed" && (
            <span className="badge badge--op-not_confirmed">operability not confirmed</span>
          )}
          {f.operability_status === "cleared" && (
            <span className="badge badge--op-cleared">operability cleared</span>
          )}
        </span>
      </summary>

      <div className="finding__detail">
        <p className="finding__source">
          {f.source_specialist}
          <span
            className="finding__match"
            title="The panel's confidence it applied the right evidence to THIS patient (separate from the evidence grade)."
          >
            match {Math.round(f.match_confidence * 100)}%
          </span>
        </p>
        <p className="finding__rec">{f.recommendation}</p>
        <p className="finding__patient">
          <strong>To address with the patient:</strong> {f.patient_facing_note}
        </p>
        <div className="finding__live">
          <strong>Live question:</strong> {f.live_question}
        </div>
        {f.transcript_ref?.quote && (
          <blockquote className="finding__quote">
            “{f.transcript_ref.quote}”
            {f.transcript_ref.speaker && <cite>— {f.transcript_ref.speaker}</cite>}
          </blockquote>
        )}
        <footer className="finding__foot">
          <span>evidence: {f.evidence_ref}</span>
          <span>rationale: {f.rationale_status.replace("_", " ")}</span>
          {f.transcript_ref?.absent && <span className="finding__absent">absence — never discussed</span>}
        </footer>
      </div>
    </details>
  );
}
