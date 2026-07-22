import type { Conflict, PanelResult, SpecialistOpinion } from "../types";

// Shows HOW the board reached its findings — the part the old single-agent UI
// had no concept of: which specialists were convened, what tensions arose between
// them, and how cross-examination settled each one. This is the transparency /
// rationale trail the panel architecture exists to provide.

const STANCE_LABEL: Record<string, string> = {
  recommend: "recommends",
  caution: "cautions",
  oppose: "opposes",
  defer: "defers",
};

function titleOf(opinions: SpecialistOpinion[], name: string): string {
  return opinions.find((o) => o.specialist === name)?.title ?? name;
}

function ConflictRow({ c, opinions }: { c: Conflict; opinions: SpecialistOpinion[] }) {
  const who = c.specialists.map((s) => titleOf(opinions, s)).join(" ↔ ");
  return (
    <li className={`conflict ${c.resolved ? "conflict--resolved" : "conflict--open"}`}>
      <div className="conflict__head">
        <span className={`badge badge--kind`}>{c.kind}</span>
        <span className="conflict__topic">{c.topic}</span>
        <span className="conflict__who">{who}</span>
        <span className={`conflict__status ${c.resolved ? "is-resolved" : "is-open"}`}>
          {c.resolved ? "✓ cross-examined" : "○ open"}
        </span>
      </div>
      <p className="conflict__desc">{c.description}</p>
      {c.resolution && <p className="conflict__res">→ {c.resolution}</p>}
    </li>
  );
}

function SpecialistOpinionCard({ o }: { o: SpecialistOpinion }) {
  const abstained = o.confidence === 0;
  return (
    <details className="opinion">
      <summary className="opinion__summary">
        <span className="opinion__title">{o.title}</span>
        <span className="opinion__meta">
          {abstained ? "abstained" : `${o.findings.length} finding${o.findings.length === 1 ? "" : "s"}`}
          {!abstained && ` · conf ${Math.round(o.confidence * 100)}%`}
        </span>
      </summary>
      <div className="opinion__body">
        <p className="opinion__text">{o.summary}</p>
        {o.claims.length > 0 && (
          <ul className="opinion__claims">
            {o.claims.map((cl, i) => (
              <li key={i}>
                <span className={`stance stance--${cl.stance}`}>{STANCE_LABEL[cl.stance] ?? cl.stance}</span>{" "}
                <span className="stance__about">{cl.about}</span> — {cl.statement}
              </li>
            ))}
          </ul>
        )}
        {o.needs.length > 0 && (
          <p className="opinion__needs">
            <strong>Needs:</strong> {o.needs.join("; ")}
          </p>
        )}
      </div>
    </details>
  );
}

export function PanelDeliberation({ result }: { result: PanelResult }) {
  const { specialists_consulted, conflicts, opinions, rounds } = result;
  return (
    <section className="panel deliberation">
      <div className="deliberation__head">
        <h2>Board deliberation</h2>
        <span className="deliberation__rounds">
          {rounds} round{rounds === 1 ? "" : "s"}
        </span>
      </div>

      <div className="specialists">
        {specialists_consulted.map((s) => (
          <span key={s} className="specialist-chip" title={titleOf(opinions, s)}>
            {titleOf(opinions, s)}
          </span>
        ))}
      </div>

      {conflicts.length > 0 ? (
        <ul className="conflicts">
          {conflicts.map((c, i) => (
            <ConflictRow key={i} c={c} opinions={opinions} />
          ))}
        </ul>
      ) : (
        <p className="deliberation__none">No contradictions between specialists — the panel agreed.</p>
      )}

      {opinions.length > 0 && (
        <details className="opinions-wrap">
          <summary>What each specialist said ({opinions.length})</summary>
          <div className="opinions">
            {opinions.map((o) => (
              <SpecialistOpinionCard key={o.specialist} o={o} />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
