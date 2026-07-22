"""Consulting one specialist — a single role-prompted Claude call over the case.

Each specialist reasons from native clinical knowledge over the clean chart +
transcript and returns a structured opinion (findings + claims + open needs).
The same function serves the parallel first pass and the cross-examination round:
pass ``cross_exam`` to hand the specialist an opposing claim to respond to.
"""
from __future__ import annotations

from .context import BoardContext
from .llm import call_json
from .roster import Specialist
from .schema import Claim, Finding, SpecialistOpinion

# The Claim schema allows four stances, but a cross-examined specialist naturally
# reaches for richer debate words ("concur", "qualify", "rebut"...). Map those to
# the canonical set rather than letting an unexpected value crash the whole run.
_STANCE_MAP = {
    "recommend": "recommend", "concur": "recommend", "agree": "recommend",
    "support": "recommend", "endorse": "recommend",
    "caution": "caution", "qualify": "caution", "conditional": "caution",
    "reconsider": "caution", "concern": "caution", "warn": "caution",
    "oppose": "oppose", "rebut": "oppose", "reject": "oppose",
    "disagree": "oppose", "against": "oppose",
    "defer": "defer", "abstain": "defer", "neutral": "defer", "unsure": "defer",
}


def _coerce_stance(value: object) -> str:
    """Map any model-produced stance to a valid one; unknown → 'caution' (a flagged
    but non-committal position, the safe default for a claim we couldn't classify)."""
    return _STANCE_MAP.get(str(value).strip().lower(), "caution")


def _parse_claims(raw: object) -> list[Claim]:
    """Build Claim objects defensively — a malformed claim is dropped, a claim with
    an unknown stance is coerced, and neither can 500 the run."""
    claims: list[Claim] = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        try:
            claims.append(Claim(
                about=str(c.get("about", "")).strip() or "unspecified",
                stance=_coerce_stance(c.get("stance")),
                statement=str(c.get("statement", "")).strip(),
            ))
        except Exception:
            continue
    return claims

# Shared framing appended to every specialist's role. This is the panel's charter:
# gap-detection, never the call; cite or it doesn't exist; two axes, not one.
_CHARTER = """
You are one voice on a tumor-board gap-detection panel. Your job is to surface what
the room did NOT adequately address from YOUR specialty's angle — not to make the
clinical decision. Hard rules:

- Every finding must cite a specific chart document (by its doc_id) or a verbatim
  transcript quote. No source, no finding. If the gap is an ABSENCE (the room never
  raised it), mark transcript_ref.absent = true.
- Keep two signals separate: recommendation_grade is the strength of the evidence
  itself (Class I–IV / Level A–C, e.g. "IIa/B"); match_confidence (0–1) is YOUR
  certainty that evidence fits THIS patient. Never merge them.
- Only set proposes_procedure=true when your finding proposes PERFORMING a surgical
  or invasive procedure — not when it merely mentions one.
- Report claims: positions you take that another specialist might contradict
  (e.g. you recommend a drug another may consider unsafe). These drive the panel's
  conflict-resolution step, so state them plainly with a stance.
- Report needs: questions only another specialist can answer.
- Stay in your lane. If something is outside your specialty, note it as a need, not
  a finding.

Return ONLY JSON matching:
{
  "summary": "2-3 sentences on what you see in this case",
  "confidence": 0.0-1.0,
  "findings": [ {
     "issue","recommendation","recommendation_grade"(or null),"match_confidence"(0-1),
     "evidence_ref","rationale_status"("stated"|"not_stated"),"patient_facing_note",
     "live_question","proposes_procedure"(bool),
     "transcript_ref": {"speaker"(or null),"quote"(or null),"absent"(bool)}
  } ],
  "claims": [ {"about","stance"("recommend"|"caution"|"oppose"|"defer"),"statement"} ],
  "needs": ["question for another specialist", ...]
}
"""


def _system(spec: Specialist) -> str:
    return f"{spec.role}\n{_CHARTER}"


def consult(
    spec: Specialist,
    ctx: BoardContext,
    cross_exam: str | None = None,
) -> SpecialistOpinion:
    """Run one specialist over the case; return its opinion.

    ``cross_exam`` (optional) appends a brokered challenge from another specialist
    the model must respond to — this is how a second opinion / rebuttal round works
    without specialists talking to each other directly."""
    user = ctx.brief()
    if cross_exam:
        user += (
            "\n\n=== SECOND-OPINION REQUEST FROM THE BOARD COORDINATOR ===\n"
            f"{cross_exam}\n"
            "Respond from your specialty: concur, qualify, or rebut, and update your "
            "findings/claims accordingly."
        )
    try:
        data, truncated = call_json(_system(spec), user)
    except Exception as e:  # a specialist that errors abstains, loudly, not silently
        return SpecialistOpinion(
            specialist=spec.name,
            title=spec.title,
            summary=f"(This specialist could not complete its review: {e})",
            confidence=0.0,
        )

    findings: list[Finding] = []
    for f in data.get("findings", []):
        f.setdefault("source_specialist", spec.name)
        try:
            findings.append(Finding(**f))
        except Exception:
            continue  # drop a malformed finding rather than fail the whole opinion

    return SpecialistOpinion(
        specialist=spec.name,
        title=spec.title,
        summary=str(data.get("summary", "")).strip(),
        findings=findings,
        claims=_parse_claims(data.get("claims")),
        needs=[str(n) for n in data.get("needs", [])],
        confidence=float(data.get("confidence", 0.5) or 0.5),
    )
