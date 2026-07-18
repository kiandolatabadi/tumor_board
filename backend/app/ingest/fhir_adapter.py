"""FHIR-envelope adapter → TumorBoardCase.

Robustness strategy:
  * value readers (`_text`, `_value`) accept BOTH full FHIR CodeableConcept /
    valueX shapes AND simplified string values, so real Abridge resources and
    hand-authored synthetic ones both parse;
  * classification is keyword-driven with an explicit `other`/`unmapped`
    fallback — an unrecognized Observation becomes a generic lab, an
    unrecognized resource type is preserved verbatim in `unmapped`;
  * nothing is required. Absent data yields an absent field, not an exception.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..case_schema import (
    Biomarker,
    BiomarkerCategory,
    CareDomain,
    Comorbidity,
    Diagnosis,
    GoalsOfCare,
    ScopeSource,
    derive_care_domains,
    ImagingReport,
    LabResult,
    Medication,
    MedIntent,
    Patient,
    PerformanceStatus,
    PriorTreatment,
    Provenance,
    Staging,
    TriState,
    TumorBoardCase,
)

# --- classification vocabularies (extend freely) ---------------------------
# gene/marker -> category. Unknown markers still classify as biomarkers if the
# observation looks molecular; otherwise they degrade to generic labs.
_BIOMARKERS: dict[str, BiomarkerCategory] = {
    "egfr": BiomarkerCategory.mutation,
    "kras": BiomarkerCategory.mutation,
    "braf": BiomarkerCategory.mutation,
    "pik3ca": BiomarkerCategory.mutation,
    "brca": BiomarkerCategory.mutation,
    "alk": BiomarkerCategory.fusion,
    "ros1": BiomarkerCategory.fusion,
    "ret": BiomarkerCategory.fusion,
    "ntrk": BiomarkerCategory.fusion,
    "met": BiomarkerCategory.mutation,
    "her2": BiomarkerCategory.expression,
    "erbb2": BiomarkerCategory.expression,
    "pd-l1": BiomarkerCategory.expression,
    "pdl1": BiomarkerCategory.expression,
    "er": BiomarkerCategory.expression,
    "pr": BiomarkerCategory.expression,
    "ki-67": BiomarkerCategory.expression,
    "msi": BiomarkerCategory.signature,
    "tmb": BiomarkerCategory.signature,
    "hrd": BiomarkerCategory.signature,
}
_PERF_HINTS = ("ecog", "karnofsky", "performance status")
_STAGE_HINTS = ("stage", "tnm")
_GOC_HINTS = ("goals of care", "goals-of-care", "advance care", "code status")
_CANCER_HINTS = ("cancer", "carcinoma", "adenocarcinoma", "sarcoma", "lymphoma",
                 "melanoma", "leukemia", "neoplasm", "tumor", "malignan")


def can_handle(record: dict) -> bool:
    return isinstance(record, dict) and "encounter_fhir" in record


def _as_str(x: Any) -> Optional[str]:
    """Coerce anything to a clean string (real records vary field shapes)."""
    if x is None or isinstance(x, str):
        return x
    return json.dumps(x, default=str)


def _patient_name(name: Any) -> Optional[str]:
    """Read a name from a plain string or a FHIR HumanName list."""
    if isinstance(name, str):
        return name
    if isinstance(name, list) and name:
        hn = name[0]
        if isinstance(hn, dict):
            if hn.get("text"):
                return hn["text"]
            given = " ".join(hn.get("given", []))
            return f"{given} {hn.get('family', '')}".strip() or None
    if isinstance(name, dict):
        return _text(name)
    return None


# --- robust value readers --------------------------------------------------
def _text(x: Any) -> Optional[str]:
    """Read a code/label from a CodeableConcept, a coding, or a plain string."""
    if x is None:
        return None
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if x.get("text"):
            return x["text"]
        codings = x.get("coding") or []
        if codings:
            c = codings[0]
            return c.get("display") or c.get("code")
    return None


def _value(obs: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (value_str, unit) across FHIR valueX shapes and simple 'value'."""
    if "valueString" in obs:
        return obs["valueString"], None
    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        return (str(q.get("value")), q.get("unit"))
    if "valueCodeableConcept" in obs:
        return _text(obs["valueCodeableConcept"]), None
    if "value" in obs:  # simplified synthetic shape
        v = obs["value"]
        return (str(v), None) if not isinstance(v, dict) else (_text(v), None)
    return None, None


def _prov(resource: dict, ref: str) -> Provenance:
    return Provenance(
        source="fhir",
        resource_type=resource.get("resourceType"),
        ref=resource.get("id") or ref,
        raw=resource,
    )


def _status_from(text: str) -> TriState:
    t = text.lower()
    if any(w in t for w in ("positive", "detected", "high", "amplified", "mutant")):
        return TriState.positive
    if any(w in t for w in ("negative", "not detected", "wild", "absent")):
        return TriState.negative
    if "equivocal" in t or "indeterminate" in t:
        return TriState.equivocal
    return TriState.unknown


# --- resource handlers -----------------------------------------------------
def _handle_observation(obs: dict, ref: str, case: TumorBoardCase) -> None:
    label = _text(obs.get("code")) or ""
    low = label.lower()
    val, unit = _value(obs)
    date = obs.get("effectiveDateTime")
    prov = _prov(obs, ref)

    if any(h in low for h in _GOC_HINTS):
        # Scope from the observation LABEL as well as its value: a "code status"
        # observation is about resuscitation even when its value is just "DNR".
        covers = derive_care_domains(label, val)
        case.goals_of_care = GoalsOfCare(
            documented_date=date, summary=val, status=None,
            covers=covers,
            scope_source=ScopeSource.derived_from_text if covers else ScopeSource.absent,
        )
        return
    if any(h in low for h in _PERF_HINTS):
        scale = "ECOG" if "ecog" in low else "Karnofsky" if "karnofsky" in low else None
        case.performance_status = PerformanceStatus(scale=scale, value=val, date=date, provenance=prov)
        return
    if any(h in low for h in _STAGE_HINTS):
        st = (case.diagnosis.staging if case.diagnosis and case.diagnosis.staging else Staging())
        st.overall_stage = st.overall_stage or (val or label)
        if case.diagnosis is None:
            case.diagnosis = Diagnosis()
        case.diagnosis.staging = st
        return

    gene = next((g for g in _BIOMARKERS if g in low), None)
    looks_molecular = gene is not None or "mutation" in low or "biomarker" in low or "tps" in low
    if looks_molecular:
        case.biomarkers.append(
            Biomarker(
                name=label,
                gene=gene.upper() if gene else None,
                category=_BIOMARKERS.get(gene, BiomarkerCategory.other),
                status=_status_from(f"{label} {val or ''}"),
                value=val,
                date=date,
                provenance=prov,
            )
        )
        return

    case.labs.append(LabResult(name=label, value=val, unit=unit, date=date, provenance=prov))


def _handle_condition(cond: dict, ref: str, case: TumorBoardCase) -> None:
    label = _text(cond.get("code")) or ""
    low = label.lower()
    prov = _prov(cond, ref)
    if any(h in low for h in _CANCER_HINTS):
        dx = case.diagnosis or Diagnosis()
        dx.primary_site = dx.primary_site or label
        dx.histology = dx.histology or label
        dx.diagnosis_date = dx.diagnosis_date or _fhir_date(cond, "onsetDateTime", "onsetPeriod", "recordedDate")
        if cond.get("stage"):  # simplified synthetic carries a stage string
            dx.staging = dx.staging or Staging(overall_stage=str(cond["stage"]))
        dx.provenance = dx.provenance or prov
        case.diagnosis = dx
    else:
        case.comorbidities.append(
            Comorbidity(name=label, severity=cond.get("severity"), provenance=prov)
        )


def _handle_medication(med: dict, ref: str, case: TumorBoardCase) -> None:
    name = _text(med.get("medicationCodeableConcept")) or med.get("medication") or _text(med.get("code"))
    if not name:
        return
    intent = MedIntent.proposed if med.get("intent") in ("proposal", "plan", "proposed") else MedIntent.current
    case.medications.append(
        Medication(name=name, intent=intent, reason=med.get("reason"), provenance=_prov(med, ref))
    )


def _handle_diagnostic_report(rep: dict, ref: str, case: TumorBoardCase) -> None:
    case.imaging.append(
        ImagingReport(
            modality=_text(rep.get("code")),
            impression=rep.get("conclusion") or _text(rep.get("code")),
            date=rep.get("effectiveDateTime"),
            provenance=_prov(rep, ref),
        )
    )


def _fhir_date(resource: dict, *keys: str) -> str | None:
    """First usable date across several FHIR spellings. Real records and
    hand-authored ones disagree: the 25 Abridge records carry `performedPeriod`
    (never `performedDateTime`), so reading only one spelling silently loses every
    procedure date — and an undated procedure cannot invalidate a goals-of-care
    record it actually postdates. Period types collapse to their start."""
    for k in keys:
        v = resource.get(k)
        if isinstance(v, dict):                       # Period: {start, end}
            v = v.get("start") or v.get("end")
        if isinstance(v, str) and v.strip():
            return v
    return None


def _handle_procedure(proc: dict, ref: str, case: TumorBoardCase) -> None:
    case.prior_treatments.append(
        PriorTreatment(
            name=_text(proc.get("code")) or "procedure",
            kind="procedure",
            date=_fhir_date(proc, "performedDateTime", "performedPeriod", "occurrenceDateTime", "performedString"),
            provenance=_prov(proc, ref),
        )
    )


_HANDLERS = {
    "Observation": _handle_observation,
    "Condition": _handle_condition,
    "MedicationRequest": _handle_medication,
    "DiagnosticReport": _handle_diagnostic_report,
    "Procedure": _handle_procedure,
}


def from_record(record: dict) -> TumorBoardCase:
    meta = record.get("metadata", {})
    pctx = record.get("patient_context", {})
    fp = pctx.get("patient") or pctx.get("Patient") or {}

    case = TumorBoardCase(
        case_id=record.get("id"),
        board_date=meta.get("date") or meta.get("board_date"),
        patient=Patient(
            id=fp.get("id"),
            name=_patient_name(fp.get("name")),
            sex=fp.get("gender"),
            birth_date=fp.get("birthDate"),
        ),
        longitudinal_summary=_as_str(pctx.get("longitudinal_summary")),
    )

    # Explicit goals_of_care extension (if a source carries it outside FHIR).
    goc = pctx.get("goals_of_care") or record.get("goals_of_care")
    if isinstance(goc, dict):
        # An explicitly coded scope wins; otherwise derive it from the prose.
        coded = goc.get("covers") or goc.get("scope")
        coded = [coded] if isinstance(coded, str) else coded
        covers, source = [], ScopeSource.absent
        if isinstance(coded, list):
            covers = [CareDomain(c) for c in coded if c in CareDomain._value2member_map_]
            source = ScopeSource.coded if covers else ScopeSource.absent
        if not covers:
            covers = derive_care_domains(goc.get("summary"), goc.get("status"))
            source = ScopeSource.derived_from_text if covers else ScopeSource.absent
        case.goals_of_care = GoalsOfCare(
            documented_date=goc.get("last_documented") or goc.get("documented_date"),
            summary=goc.get("summary"),
            status=goc.get("status"),
            covers=covers,
            scope_source=source,
        )

    enc = record.get("encounter_fhir", {})
    # Real contract nests resources under related_resources; simplified synthetic
    # may group them directly. Handle both.
    groups = enc.get("related_resources", enc)
    if isinstance(groups, dict):
        for rtype, resources in groups.items():
            if rtype == "encounter" or not isinstance(resources, list):
                continue
            handler = _HANDLERS.get(rtype)
            for i, res in enumerate(resources):
                if not isinstance(res, dict):
                    continue
                if handler:
                    handler(res, f"{rtype}[{i}]", case)
                else:
                    case.unmapped.append(res)  # lossless
    return case
