"""The orchestrator: one Claude Messages call with tool_use (README §5).

Flow: feed the transcript + chart + canned tables to Claude, let it call the
sub-check tools, then have it emit findings + an action ledger as JSON. The
operability gate is enforced HERE in code, after the model returns — a surgical
finding without a cleared operability result is relabeled, never surfaced clean.
"""
from __future__ import annotations

import json
import re

from . import tools
from .agents.schema import Enrichment
from .case_schema import TumorBoardCase
from .config import MAX_TOOL_TURNS, MODEL, get_client
from .goc import GocEvaluation, evaluate_goc
from .schema import ActionItem, AnalysisResult, Finding, OperabilityStatus

SYSTEM = """You are the orchestrator for a tumor-board gap-detection assistant.
You surface what the room did NOT address; you never make the clinical call.

Given the patient chart and the board transcript, use the provided tools to check
guideline coverage, trial eligibility, drug interactions, stale data, and operability.
Every finding must cite a source you actually retrieved via a tool — no source, no finding.

Rules:
- Any option involving surgery or an invasive procedure REQUIRES a check_operability
  call first. Never present a surgical option as ready without it.
- Set proposes_procedure=true ONLY when a finding proposes performing a surgical or
  invasive procedure — not when it merely mentions one (e.g. a documentation gap
  about "radiotherapy vs surgery" is not a procedure proposal).
- Keep recommendation_grade (evidence strength, e.g. "IIa/B") separate from
  match_confidence (your certainty this evidence fits THIS patient, 0-1).
- The GOALS-OF-CARE PRECONDITION has already been evaluated in code; treat it as
  authoritative and never contradict it. If its status is not
  "valid_escalation_consistent", any escalating option you surface must state the
  goals-of-care status alongside it — the patient's documented wishes are context
  for every recommendation, not a separate topic.
- Link each finding to the transcript line/quote it relates to, or mark it an absence.

When done calling tools, return ONLY a JSON object matching:
{"findings": [Finding...], "action_ledger": [ActionItem...]}
where Finding has: issue, evidence_ref, recommendation, recommendation_grade,
match_confidence, rationale_status ("stated"|"not_stated"), patient_facing_note,
live_question, source_agent, proposes_procedure (bool),
operability_status ("not_applicable"|"cleared"|"not_confirmed"),
transcript_ref {line, timestamp, speaker, quote}.
ActionItem has: action, owner, deadline, linked_finding.
"""

# Backstop for when the model forgets to set proposes_procedure: the RECOMMENDATION
# must both name a procedure AND propose doing it. This avoids the false positive
# where a finding merely *mentions* surgery (e.g. "document rationale for
# radiotherapy over resection") — mention is not a proposal.
_PROC_NOUN = re.compile(
    r"\b(surg\w*|resect\w+|lobectom\w+|pneumonectom\w+|biops\w+|ablat\w+|"
    r"invasive procedure|operat\w+)\b",
    re.I,
)
_PROPOSE_VERB = re.compile(
    r"\b(offer\w*|proceed\w*|perform\w*|schedul\w*|pursu\w*|undergo\w*|opt for|recommend\w*)\b",
    re.I,
)


def _proposes_procedure(f: Finding) -> bool:
    if f.proposes_procedure:  # primary: the model's declared intent
        return True
    rec = f.recommendation     # backstop: verb + noun in the recommendation only
    return bool(_PROC_NOUN.search(rec) and _PROPOSE_VERB.search(rec))


def gate_operability(
    findings: list[Finding],
    operability_results: list[dict] = (),
) -> list[Finding]:
    """Enforce the hard rule in code. A finding that PROPOSES a procedure may only
    stand as `cleared` if an actual check_operability result cleared it; otherwise
    it is forced to `not_confirmed`. A blocking result (cleared=False) overrides
    even a model-declared `cleared`. This makes the tool result *required* before
    a surgical option can be emitted as ready — not prompt-mediated."""
    blocking = any(r.get("cleared") is False for r in operability_results)
    cleared_exists = any(r.get("cleared") is True for r in operability_results)
    for f in findings:
        if not _proposes_procedure(f):
            continue
        if (blocking or not cleared_exists) and f.operability_status != OperabilityStatus.not_confirmed:
            f.operability_status = OperabilityStatus.not_confirmed
            f.recommendation = (
                f"{f.recommendation}  [guideline-preferred — operability not yet confirmed]"
            )
    return findings


def goc_skip_result(goc: GocEvaluation, enrichment: Enrichment | None) -> AnalysisResult:
    """The skip path. Guidance is skipped, but the SKIP ITSELF IS SURFACED — a
    system that declines to recommend must say so, or the clinician cannot tell
    the difference between 'nothing applies' and 'nothing was looked for'."""
    return AnalysisResult(
        findings=[
            Finding(
                issue="Disease-directed guidance and trial matching were not surfaced for this case.",
                evidence_ref=f"goals_of_care@{goc.documented_date}",
                recommendation=goc.disclosure,
                recommendation_grade=None,  # no guidance rule matched — nothing to copy a grade from
                match_confidence=1.0,       # a deterministic record check, not a semantic match
                patient_facing_note=(
                    "Care is being guided by the goals this patient already documented, which focus on "
                    "comfort and support rather than further disease-directed treatment."
                ),
                live_question=(
                    "Do the documented goals of care still reflect what this patient wants today?"
                ),
                source_agent="goals_of_care_precondition",
                proposes_procedure=False,
            )
        ],
        action_ledger=[
            ActionItem(
                action="Confirm the documented goals of care still reflect the patient's wishes.",
                owner="NURSE_COORDINATOR",
                linked_finding="Disease-directed guidance and trial matching were not surfaced for this case.",
            )
        ],
        enrichment=enrichment or Enrichment(),
        goc=goc,
    )


def _operability_input(case: TumorBoardCase, obs) -> dict:
    """Derive check_operability inputs from the case, folding in the inferred fact
    that raised the check so an *uncoded* comorbidity actually influences the result."""
    ecog = None
    if case.performance_status and case.performance_status.value:
        m = re.search(r"\d", case.performance_status.value)
        ecog = int(m.group()) if m else None
    comorbidities = [c.name for c in case.comorbidities]
    comorbidities.append(obs.value or obs.summary)  # the inferred comorbidity/symptom
    return {"procedure": "proposed surgical/invasive procedure", "ecog_status": ecog, "comorbidities": comorbidities}


def run_triggered_checks(case: TumorBoardCase, enrichment: Enrichment | None) -> list[dict]:
    """Deterministically run any tool an inferred observation raised. This closes
    the enrichment loop: an inferred 'uncoded COPD — surgery may be unsafe' with
    raises_check=check_operability runs the check in code, and its result gates the
    findings below — the whole reason the enrichment channel exists."""
    if not enrichment:
        return []
    triggered: list[dict] = []
    for obs in enrichment.inferred:
        if not obs.raises_check:
            continue
        tool = obs.raises_check.value
        tool_input = _operability_input(case, obs) if tool == "check_operability" else {}
        try:
            result = tools.dispatch(tool, tool_input)
        except TypeError:
            # Tool needs inputs we can't derive from an inference alone; record intent.
            result = {"error": "insufficient inputs to run deterministically", "needs_inputs": True}
        triggered.append({"raised_by": obs.summary, "tool": tool, "input": tool_input, "result": result})
    return triggered


def analyze(
    case: TumorBoardCase,
    transcript: list[dict],
    enrichment: Enrichment | None = None,
) -> AnalysisResult:
    # PRECONDITION, before anything else: does this patient want disease-directed
    # care at all? Only a positive, recent, event-valid supportive-care record can
    # authorize skipping guidance — absence or staleness never does. Runs after
    # enrichment because the room may hold fresher goals of care than the chart.
    goc = evaluate_goc(case, enrichment)
    if goc.authorizes_skip:
        return goc_skip_result(goc, enrichment)

    client = get_client()
    # The normalized case is what the model reasons over; its own completeness
    # check surfaces the structural gaps (missing stage, biomarkers, GOC...).
    gaps = [m.model_dump() for m in case.completeness()]
    inferred = [o.model_dump() for o in enrichment.inferred] if enrichment else []

    # Deterministically run any check an inference raised, BEFORE the model reasons.
    triggered = run_triggered_checks(case, enrichment)
    # Operability results gate the findings; seed with the triggered ones.
    op_results = [t["result"] for t in triggered if t["tool"] == "check_operability"]

    user_content = (
        "NORMALIZED PATIENT CASE:\n"
        + json.dumps(case.model_dump(), indent=2, default=str)
        + "\n\nSTRUCTURAL GAPS (absent oncology essentials):\n"
        + json.dumps(gaps, indent=2)
        + "\n\nINFERRED CONTEXT (source-cited but UNCONFIRMED — treat as leads, "
        "verify against the transcript quote before acting):\n"
        + json.dumps(inferred, indent=2, default=str)
        + "\n\nTRIGGERED CHECKS (AUTHORITATIVE — these tools already ran because an "
        "inference raised them; respect their results):\n"
        + json.dumps(triggered, indent=2, default=str)
        + "\n\nGOALS-OF-CARE PRECONDITION (AUTHORITATIVE — already evaluated in code):\n"
        + json.dumps(goc.model_dump(), indent=2, default=str)
        + "\n\nBOARD TRANSCRIPT:\n"
        + json.dumps(transcript, indent=2)
    )
    messages = [{"role": "user", "content": user_content}]

    for _ in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM,
            tools=tools.TOOL_DEFS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            result = _parse(resp)
            result.findings = gate_operability(result.findings, op_results)
            result.enrichment = enrichment or Enrichment()
            result.triggered_checks = triggered
            result.goc = goc
            if goc.revisit_recommended:
                result.action_ledger.append(
                    ActionItem(
                        action=f"Revisit goals of care with the patient — {goc.disclosure}",
                        owner="NURSE_COORDINATOR",
                    )
                )
            return result

        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = tools.dispatch(block.name, block.input)
                if block.name == "check_operability":
                    op_results.append(out)  # capture the model's own operability calls
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out),
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Orchestrator exceeded {MAX_TOOL_TURNS} tool turns without finishing.")


def _parse(resp) -> AnalysisResult:
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    # Tolerate ```json fences.
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    data = json.loads(text)
    return AnalysisResult(**data)  # gating applied by analyze() with operability results
