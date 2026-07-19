import type { Finding } from "../types";
import { FindingCard } from "./FindingCard";

// Order findings by clinical grade: Class of Recommendation (I, IIa, IIb, III, IV)
// then Level of Evidence (A, B, C), so I/A leads and the weakest trail. Ungraded
// findings sort last. Numbering follows this order.
const CLASS_ORDER: Record<string, number> = { I: 0, IIa: 1, IIb: 2, II: 1, III: 3, IV: 4 };
const LOE_ORDER: Record<string, number> = { A: 0, B: 1, C: 2 };

function gradeRank(grade: string | null): number {
  if (!grade) return 999;
  const [cls = "", loe = ""] = grade.split("/").map((s) => s.trim());
  const c = CLASS_ORDER[cls] ?? 5;
  const l = LOE_ORDER[loe.toUpperCase()] ?? 3;
  return c * 10 + l;
}

export function FindingsPanel({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className="empty">No findings yet — run the analysis.</p>;
  }
  const ordered = [...findings].sort(
    (a, b) => gradeRank(a.recommendation_grade) - gradeRank(b.recommendation_grade),
  );
  return (
    <section className="panel">
      <h2>Findings ({findings.length})</h2>
      {ordered.map((f, i) => (
        <FindingCard key={i} f={f} index={i + 1} />
      ))}
    </section>
  );
}
