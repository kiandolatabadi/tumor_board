"""The orchestrator: one Claude Messages call with tool_use (README §5).

Flow: feed the transcript + chart + canned tables to Claude, let it call the
sub-check tools, then have it emit findings + an action ledger as JSON. The
operability gate is enforced HERE in code, after the model returns — a surgical
finding without a cleared operability result is relabeled, never surfaced clean.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from . import tools
from .agents.schema import Enrichment
from .case_schema import TumorBoardCase
from .config import MAX_OUTPUT_TOKENS, MAX_TOOL_TURNS, MODEL, get_client
from .goc import GocEvaluation, evaluate_goc
from .schema import ActionItem, AnalysisResult, Finding, OperabilityStatus

SYSTEM = """You are the orchestrator for a tumor-board gap-detection assistant.
You surface what the room did NOT address; you never make the clinical call.

The sub-checks — guideline coverage, trial eligibility, drug interactions, stale
data, and operability — have ALREADY been run for you in code. Their outputs are
provided below under TOOL RESULTS. Synthesize the gap findings from those results,
the patient case, and the board transcript. Every finding must cite a source from
the provided data — no source, no finding.

Rules:
- Set proposes_procedure=true ONLY when a finding proposes performing a surgical or
  invasive procedure — not when it merely mentions one (e.g. a documentation gap
  about "radiotherapy vs surgery" is not a procedure proposal). Do not present a
  surgical option as ready unless the provided operability result cleared it.
- Keep recommendation_grade (evidence strength, e.g. "IIa/B") separate from
  match_confidence (your certainty this evidence fits THIS patient, 0-1).
- The GOALS-OF-CARE PRECONDITION has already been evaluated in code; treat it as
  authoritative and never contradict it. If its status is not
  "valid_escalation_consistent", any escalating option you surface must state the
  goals-of-care status alongside it — the patient's documented wishes are context
  for every recommendation, not a separate topic.
- Link each finding to the transcript line/quote it relates to, or mark it an absence.

Return ONLY a JSON object matching:
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


_SKIP_ISSUE = "Disease-directed guidance and trial matching were not surfaced for this case."


def goc_skip_result(goc: GocEvaluation, enrichment: Enrichment | None) -> AnalysisResult:
    """The narrowed-scope path. DISEASE-DIRECTED guidance is skipped; symptom-directed
    care is not — a supportive-care record narrows the scope, it does not empty it.

    The skip ITSELF IS SURFACED: a system that declines to recommend must say so, or
    the clinician cannot tell 'nothing applies' from 'nothing was looked for'."""
    return AnalysisResult(
        findings=[
            Finding(
                issue=_SKIP_ISSUE,
                evidence_ref=f"goals_of_care@{goc.documented_date}",
                recommendation=goc.disclosure,
                recommendation_grade=None,  # no guidance rule matched — nothing to copy a grade from
                match_confidence=1.0,       # a deterministic record check, not a semantic match
                patient_facing_note=(
                    "Care is being guided by the goals this patient already documented, which focus on "
                    "comfort and support rather than further disease-directed treatment. Treatments that "
                    "relieve symptoms remain available."
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
                linked_finding=_SKIP_ISSUE,
            ),
            ActionItem(
                action=(
                    "Review symptom-directed options (e.g. palliative radiotherapy, symptom control) — "
                    "in scope despite the supportive-care goals, and not covered by this run."
                ),
                owner="ONCOLOGIST",
                linked_finding=_SKIP_ISSUE,
            ),
        ],
        enrichment=enrichment or Enrichment(),
        goc=goc,
    )



def _unparseable_result(detail: str, stop_reason: str | None) -> AnalysisResult:
    """Degraded result for output we could not read at all. Reports the failure as
    a finding so the run is visibly incomplete rather than visibly empty."""
    return AnalysisResult(
        findings=[
            Finding(
                issue="Analysis did not complete — the model's output could not be read.",
                evidence_ref=f"orchestrator/parse_error (stop_reason={stop_reason})",
                recommendation=(
                    "Re-run the analysis. No findings were produced, which is NOT the same as "
                    f"finding no gaps. Parser detail: {detail[:200]}"
                ),
                match_confidence=1.0,
                patient_facing_note="Not applicable — this is a system message, not a clinical finding.",
                live_question="Re-run the analysis before relying on this case's findings.",
                source_agent="orchestrator",
                proposes_procedure=False,
            )
        ],
        action_ledger=[],
        truncated=True,
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


# --- deterministic tool sweep (Option 1: no multi-round tool loop) -----------
_CANCER_KEYWORDS = (
    ("breast", "breast"), ("nsclc", "lung"), ("lung", "lung"), ("colorectal", "colorectal"),
    ("colon", "colorectal"), ("prostate", "prostate"), ("ovarian", "ovarian"),
    ("melanoma", "melanoma"), ("pancrea", "pancreatic"),
)


def _cancer_type(case: TumorBoardCase):
    dx = case.diagnosis
    blob = " ".join(filter(None, [dx.primary_site, dx.histology])).lower() if dx else ""
    for kw, ct in _CANCER_KEYWORDS:
        if kw in blob:
            return ct
    return dx.primary_site if dx else None


def _age_years(case: TumorBoardCase):
    from datetime import date
    try:
        b = date.fromisoformat(case.patient.birth_date[:10])
        ref = date.fromisoformat((case.board_date or b.isoformat())[:10])
        return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))
    except (TypeError, ValueError):
        return None


def _ecog(case: TumorBoardCase):
    if case.performance_status and case.performance_status.value:
        m = re.search(r"\d", case.performance_status.value)
        return int(m.group()) if m else None
    return None


# Drug -> therapy class. Scanned across current meds AND the transcript, so the
# board's PLANNED therapy (which the model used to infer, e.g. planned ribociclib
# gating fertility coverage) still reaches the guideline agent deterministically.
_DRUG_CLASS = {
    "ribociclib": "gonadotoxic", "palbociclib": "gonadotoxic", "abemaciclib": "gonadotoxic",
    "cyclophosphamide": "gonadotoxic", "doxorubicin": "gonadotoxic", "capecitabine": "gonadotoxic",
    "paclitaxel": "gonadotoxic", "docetaxel": "gonadotoxic", "carboplatin": "gonadotoxic",
    "cisplatin": "gonadotoxic", "chemotherapy": "gonadotoxic",
    "tamoxifen": "endocrine", "fulvestrant": "endocrine", "letrozole": "endocrine",
    "anastrozole": "endocrine", "exemestane": "endocrine",
}


def _therapy_and_drugs(case: TumorBoardCase, transcript: list[dict]) -> tuple[list[str], list[str]]:
    text = (" ".join(m.name.lower() for m in case.medications) + " "
            + " ".join(str(t.get("text", "")).lower() for t in transcript))
    classes, drugs = set(), set()
    for drug, cls in _DRUG_CLASS.items():
        if drug in text:
            classes.add(cls)
            drugs.add(drug)
    return sorted(classes), sorted(drugs)


def _sweep_tools(case: TumorBoardCase, transcript: list[dict]) -> dict:
    """Run every sub-check in code, deriving inputs from the case (and a deterministic
    scan of the transcript for planned therapy). Replaces the model orchestrating
    tool calls across many rounds."""
    dx = case.diagnosis
    cancer = _cancer_type(case)
    stage = dx.staging.overall_stage if dx and dx.staging else None
    biomarkers = [b.gene or b.name for b in case.biomarkers]
    therapy_class, planned_drugs = _therapy_and_drugs(case, transcript)
    meds = [m.name for m in case.medications] + [d for d in planned_drugs if d not in {m.name.lower() for m in case.medications}]
    comorbid = [c.name for c in case.comorbidities]
    out: dict = {}

    if cancer:
        out["check_guideline_coverage"] = tools.dispatch("check_guideline_coverage", {
            "cancer_type": cancer, "stage": stage, "biomarkers": biomarkers,
            "age": _age_years(case), "sex": case.patient.sex, "therapy_class": therapy_class,
        })
        out["search_trials"] = tools.dispatch("search_trials", {
            "biomarkers": biomarkers, "cancer_type": cancer, "stage": stage,
        })
    if meds:
        seen, inter = set(), []
        for m in meds:
            for it in tools.dispatch("check_drug_interactions", {"proposed_drug": m, "current_meds": meds}).get("interactions", []):
                key = tuple(sorted([str(it.get("drug_a", "")), str(it.get("drug_b", ""))]))
                if key not in seen:
                    seen.add(key)
                    inter.append(it)
        out["check_drug_interactions"] = {"interactions": inter, "current_meds": meds}

    fields = [{"name": f"lab: {l.name}", "last_updated": l.date} for l in case.labs if l.date]
    fields += [{"name": f"imaging: {i.modality or 'study'}", "last_updated": i.date} for i in case.imaging if i.date]
    if fields and case.board_date:
        out["flag_stale_data"] = tools.dispatch("flag_stale_data", {"fields": fields, "as_of": case.board_date})

    if comorbid or _ecog(case) is not None:
        out["check_operability"] = tools.dispatch("check_operability", {
            "procedure": "proposed surgical/invasive procedure",
            "ecog_status": _ecog(case), "comorbidities": comorbid,
        })
    return out


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

    # Deterministically run any check an inference raised, plus the full tool sweep.
    triggered = run_triggered_checks(case, enrichment)
    tool_results = _sweep_tools(case, transcript)

    # Operability results gate the findings: the inference-triggered ones + the sweep's.
    op_results = [t["result"] for t in triggered if t["tool"] == "check_operability"]
    if "check_operability" in tool_results:
        op_results.append(tool_results["check_operability"])

    user_content = (
        "NORMALIZED PATIENT CASE:\n"
        + json.dumps(case.model_dump(), indent=2, default=str)
        + "\n\nSTRUCTURAL GAPS (absent oncology essentials):\n"
        + json.dumps(gaps, indent=2)
        + "\n\nINFERRED CONTEXT (source-cited but UNCONFIRMED — treat as leads, "
        "verify against the transcript quote before acting):\n"
        + json.dumps(inferred, indent=2, default=str)
        + "\n\nTRIGGERED CHECKS (raised by an inference):\n"
        + json.dumps(triggered, indent=2, default=str)
        + "\n\nGOALS-OF-CARE PRECONDITION (AUTHORITATIVE — already evaluated in code):\n"
        + json.dumps(goc.model_dump(), indent=2, default=str)
        + "\n\nTOOL RESULTS (the sub-checks, already run in code):\n"
        + json.dumps(tool_results, indent=2, default=str)
        + "\n\nBOARD TRANSCRIPT:\n"
        + json.dumps(transcript, indent=2)
    )

    # ONE synthesis call — no tool loop. Cache the (static) system prompt across runs.
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    try:
        result = _parse(resp)
    except OutputUnparseable as e:
        # Loud, not silent: an empty findings panel is indistinguishable from
        # "this case had no gaps", which is the worst failure here.
        result = _unparseable_result(str(e), resp.stop_reason)
    if resp.stop_reason == "max_tokens":
        result.truncated = True
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


class OutputUnparseable(Exception):
    """The model's final message could not be read as the agreed JSON."""


def _salvage_findings(text: str) -> list[dict]:
    """Best-effort recovery from truncated output. Scans the findings array and
    keeps every COMPLETE object, so a run cut off mid-array yields 6 findings
    instead of none. Partial trailing objects are discarded, never guessed at."""
    start = text.find('"findings"')
    if start < 0:
        return []
    i = text.find("[", start)
    if i < 0:
        return []
    out, depth, obj_start, in_str, esc = [], 0, None, False, False
    for j in range(i + 1, len(text)):
        c = text[j]
        if in_str:
            in_str = not (c == '"' and not esc)
            esc = c == "\\" and not esc
            continue
        if c == '"':
            in_str, esc = True, False
        elif c == "{":
            if depth == 0:
                obj_start = j
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    out.append(json.loads(text[obj_start:j + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
        elif c == "]" and depth == 0:
            break
    return out


def _parse(resp) -> AnalysisResult:
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    # Tolerate ```json fences.
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        return AnalysisResult(**json.loads(text))  # gating applied by analyze()
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # Truncated or malformed. Recover whole findings rather than losing the run:
        # a blank panel is indistinguishable from "nothing was wrong with this case".
        salvaged = []
        for f in _salvage_findings(text):
            try:
                salvaged.append(Finding(**f))
            except ValidationError:
                continue
        if not salvaged:
            raise OutputUnparseable(str(e)) from e
        return AnalysisResult(findings=salvaged, action_ledger=[], truncated=True)
