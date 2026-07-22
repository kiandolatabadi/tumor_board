"""Synthesis: merge the specialists' opinions + the deliberation into one board output.

A single Claude call de-duplicates overlapping findings, ranks them by clinical
grade (I/A first), folds in how cross-examination settled each conflict, and emits
the end-of-meeting action ledger. It does NOT invent findings — it may only keep,
merge, or drop what the specialists produced, preserving each finding's source.
"""
from __future__ import annotations

from .context import BoardContext
from .llm import call_json
from .schema import (
    ActionItem,
    Conflict,
    DeliberationEntry,
    Finding,
    SpecialistOpinion,
)

_SYSTEM = (
    "You are the tumor-board coordinator writing up the panel's conclusions. You are "
    "given every specialist's opinion, the conflicts found between them, and how the "
    "cross-examination resolved each one. Produce the final board output.\n\n"
    "Rules:\n"
    "- Do NOT invent findings. Keep, merge (when two specialists raised the same gap), "
    "or drop the specialists' findings. Every kept finding must retain a real "
    "evidence_ref and name its source_specialist.\n"
    "- When a conflict was resolved, reflect the resolution: if cardiology's caution "
    "overrode oncology's recommendation, the surviving finding must say so.\n"
    "- Order findings by clinical grade — Class I / Level A first, ungraded last.\n"
    "- Keep recommendation_grade (evidence strength) and match_confidence (fit to THIS "
    "patient) separate. Never present a procedure as ready; leave operability wording "
    "to the panel's gate.\n"
    "- Build an action_ledger of concrete human to-dos pulled from what the room and "
    "specialists said needs doing: {action, owner (a role), deadline (or null), "
    "linked_finding (the issue text)}.\n\n"
    "Return ONLY JSON: {\"findings\": [Finding...], \"action_ledger\": [ActionItem...]} "
    "where Finding has: issue, recommendation, recommendation_grade(or null), "
    "match_confidence(0-1), evidence_ref, rationale_status(\"stated\"|\"not_stated\"), "
    "patient_facing_note, live_question, source_specialist, proposes_procedure(bool), "
    "operability_status(\"not_applicable\"|\"cleared\"|\"not_confirmed\"), "
    "transcript_ref{speaker,quote,absent}."
)


def _opinions_block(opinions: list[SpecialistOpinion]) -> str:
    parts = []
    for o in opinions:
        fnd = "\n".join(
            f"    - [{f.recommendation_grade or 'ungraded'}] {f.issue} "
            f"(src {f.source_specialist}, ev {f.evidence_ref})"
            for f in o.findings
        ) or "    (no findings)"
        parts.append(f"### {o.specialist} ({o.title})\n  summary: {o.summary}\n  findings:\n{fnd}")
    return "\n\n".join(parts)


def _conflicts_block(conflicts: list[Conflict], deliberation: list[DeliberationEntry]) -> str:
    if not conflicts:
        return "(no conflicts found)"
    lines = []
    for c in conflicts:
        status = f"RESOLVED: {c.resolution}" if c.resolved else "UNRESOLVED"
        lines.append(f"- [{c.kind}] {c.topic} ({', '.join(c.specialists)}) — {c.description} — {status}")
    log = "\n".join(f"  · round {d.round} → {d.prompt_to}: {d.response[:400]}" for d in deliberation)
    return "\n".join(lines) + (f"\n\nCross-examination log:\n{log}" if log else "")


def synthesize(
    ctx: BoardContext,
    opinions: list[SpecialistOpinion],
    conflicts: list[Conflict],
    deliberation: list[DeliberationEntry],
) -> tuple[list[Finding], list[ActionItem], bool]:
    """Return (ranked findings, action ledger, truncated?)."""
    all_findings = [f for o in opinions for f in o.findings]
    if not all_findings:
        return [], [], False

    user = (
        f"CASE: {ctx.identity}\n\n"
        f"SPECIALIST OPINIONS:\n{_opinions_block(opinions)}\n\n"
        f"CONFLICTS & RESOLUTION:\n{_conflicts_block(conflicts, deliberation)}\n\n"
        f"FULL FINDINGS (verbatim, for merge/rank — do not lose sources):\n"
        + "\n".join(f.model_dump_json() for f in all_findings)
    )
    try:
        data, truncated = call_json(_SYSTEM, user, max_tokens=6000)
    except Exception:
        # Fall back to the raw union rather than losing the run entirely.
        return all_findings, [], True

    findings: list[Finding] = []
    for f in data.get("findings", []):
        try:
            findings.append(Finding(**f))
        except Exception:
            continue
    if not findings:
        findings = all_findings  # never let synthesis silently empty the panel

    ledger: list[ActionItem] = []
    for a in data.get("action_ledger", []):
        try:
            ledger.append(ActionItem(**a))
        except Exception:
            continue
    return findings, ledger, truncated
