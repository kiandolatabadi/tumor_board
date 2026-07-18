"""Stage 2 adapter: FHIR-shaped source record → PatientCaseBundle (contract §2).

Mechanical only. No clinical judgment, no "gap". Reuses the low-level FHIR value
readers and classification vocabularies from the pre-split ingest adapter (single
source for that logic) but emits stable element_ids, a raw_ref side-car, and the
mechanical presence/staleness statements.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..ingest.fhir_adapter import (
    _BIOMARKERS,
    _CANCER_HINTS,
    _GOC_HINTS,
    _PERF_HINTS,
    _STAGE_HINTS,
    _status_from,
    _text,
    _value,
)
from .bundle import (
    BUNDLE_VERSION,
    AdapterReport,
    Biomarker,
    Comorbidity,
    Diagnosis,
    GoalsOfCare,
    ImagingReport,
    LabResult,
    Medication,
    Patient,
    PatientCaseBundle,
    PerformanceStatus,
    PresenceEntry,
    PriorTreatment,
    Provenance,
    REQUIRED_SELECTORS,
    Staging,
    Staleness,
)
from .enums import (BiomarkerCategory, CareDomain, MedIntent, PerfScale, ScopeSource, StageGroup,
                    TreatmentKind, TriState, classify_treatment_kind,
                    derive_care_domains)
from .ids import age_days, age_years, element_id, source_digest, stage_group, value_num

# Treatment-kind classification lives in app/treatment_kinds.py so the Stage 2
# contract and the pre-split adapter cannot drift apart.
_treatment_kind = classify_treatment_kind


def _as_str(x: Any) -> Optional[str]:
    if x is None or isinstance(x, str):
        return x
    return json.dumps(x, default=str)


class _Builder:
    """Carries the per-run mutable state (seen ids, raw side-car, report counters)."""

    def __init__(self, bundle: PatientCaseBundle):
        self.b = bundle
        self.seen: set[str] = set()
        self.warnings: list[str] = []
        self.seen_count = 0
        self.mapped = 0

    def eid(self, collection: str, label: str, *, dated=None, resource=None) -> str:
        return element_id(collection, label, self.seen, dated=dated, resource=resource)

    def prov(self, raw_ref: str, resource: dict) -> Provenance:
        self.b.raw_resources[raw_ref] = resource  # side-car, not inlined
        return Provenance(source="fhir", resource_type=resource.get("resourceType"),
                          ref=resource.get("id"), raw_ref=raw_ref)


def _handle_observation(res: dict, bld: _Builder) -> bool:
    b = bld.b
    label = _text(res.get("code")) or ""
    low = label.lower()
    val, unit = _value(res)
    dated = res.get("effectiveDateTime")

    if any(h in low for h in _GOC_HINTS):
        if b.goals_of_care is None:
            eid = bld.eid("goals_of_care", label or "documented", resource=res)
            covers = derive_care_domains(label, val)
            b.goals_of_care = GoalsOfCare(
                element_id=eid, documented_date=dated, summary=val,
                covers=covers,
                scope_source=ScopeSource.derived_from_text if covers else ScopeSource.absent,
                provenance=bld.prov(eid, res))
        return True
    if any(h in low for h in _PERF_HINTS):
        eid = bld.eid("performance_status", label or "ecog", resource=res)
        scale = PerfScale.ECOG if "ecog" in low else PerfScale.Karnofsky if "karnofsky" in low else None
        b.performance_status = PerformanceStatus(element_id=eid, scale=scale, value=val, value_num=value_num(val), date=dated, provenance=bld.prov(eid, res))
        return True
    if any(h in low for h in _STAGE_HINTS):
        if b.diagnosis is None:
            eid = bld.eid("diagnosis", "primary", resource=res)
            b.diagnosis = Diagnosis(element_id=eid, provenance=bld.prov(eid, res))
        st = b.diagnosis.staging or Staging()
        st.overall_stage = st.overall_stage or (val or label)
        st.stage_group = StageGroup(stage_group(st.overall_stage))
        b.diagnosis.staging = st
        return True

    gene = next((g for g in _BIOMARKERS if g in low), None)
    if gene or "mutation" in low or "biomarker" in low or "tps" in low:
        eid = bld.eid("biomarkers", label, resource=res)
        category = BiomarkerCategory(_BIOMARKERS[gene].value) if gene else BiomarkerCategory.other
        b.biomarkers.append(Biomarker(
            element_id=eid, name=label, gene=gene.upper() if gene else None, category=category,
            status=TriState(_status_from(f"{label} {val or ''}").value),
            value=val, value_num=value_num(val), unit=unit, date=dated, provenance=bld.prov(eid, res)))
        return True

    eid = bld.eid("labs", label, dated=dated, resource=res)
    b.labs.append(LabResult(element_id=eid, name=label, value=val, value_num=value_num(val), unit=unit, date=dated, provenance=bld.prov(eid, res)))
    return True


def _handle_condition(res: dict, bld: _Builder) -> bool:
    b = bld.b
    label = _text(res.get("code")) or ""
    if any(h in label.lower() for h in _CANCER_HINTS):
        if b.diagnosis is None:
            eid = bld.eid("diagnosis", "primary", resource=res)
            b.diagnosis = Diagnosis(element_id=eid, provenance=bld.prov(eid, res))
        dx = b.diagnosis
        dx.primary_site = dx.primary_site or label
        dx.histology = dx.histology or label
        dx.diagnosis_date = dx.diagnosis_date or res.get("onsetDateTime")
        if res.get("stage"):
            st = dx.staging or Staging()
            st.overall_stage = st.overall_stage or str(res["stage"])
            st.stage_group = StageGroup(stage_group(st.overall_stage))
            dx.staging = st
        return True
    eid = bld.eid("comorbidities", label, resource=res)
    b.comorbidities.append(Comorbidity(element_id=eid, name=label, severity=res.get("severity"), provenance=bld.prov(eid, res)))
    return True


def _handle_medication(res: dict, bld: _Builder) -> bool:
    name = _text(res.get("medicationCodeableConcept")) or res.get("medication") or _text(res.get("code"))
    if not name:
        return False
    intent = MedIntent.proposed if res.get("intent") in ("proposal", "plan", "proposed") else MedIntent.current
    eid = bld.eid("medications", name, resource=res)
    bld.b.medications.append(Medication(element_id=eid, name=name, intent=intent, reason=res.get("reason"), provenance=bld.prov(eid, res)))
    return True


def _handle_diagnostic_report(res: dict, bld: _Builder) -> bool:
    modality = _text(res.get("code"))
    dated = res.get("effectiveDateTime")
    eid = bld.eid("imaging", modality or "report", dated=dated, resource=res)
    bld.b.imaging.append(ImagingReport(element_id=eid, modality=modality, impression=res.get("conclusion") or modality, date=dated, provenance=bld.prov(eid, res)))
    return True


def _handle_procedure(res: dict, bld: _Builder) -> bool:
    name = _text(res.get("code")) or "procedure"
    dated = res.get("performedDateTime")
    eid = bld.eid("prior_treatments", name, dated=dated, resource=res)
    bld.b.prior_treatments.append(PriorTreatment(element_id=eid, name=name, kind=_treatment_kind(name), date=dated, provenance=bld.prov(eid, res)))
    return True


_HANDLERS = {
    "Observation": _handle_observation,
    "Condition": _handle_condition,
    "MedicationRequest": _handle_medication,
    "DiagnosticReport": _handle_diagnostic_report,
    "Procedure": _handle_procedure,
}


def _build_presence(b: PatientCaseBundle) -> dict[str, PresenceEntry]:
    def entry(ids: list[str]) -> PresenceEntry:
        ids = [i for i in ids if i]
        return PresenceEntry(present=bool(ids), element_ids=ids, count=len(ids))

    dx = b.diagnosis
    st = dx.staging if dx else None
    return {
        "diagnosis.primary_site": entry([dx.element_id] if dx and dx.primary_site else []),
        "diagnosis.histology": entry([dx.element_id] if dx and dx.histology else []),
        "diagnosis.staging.overall_stage": entry([dx.element_id] if st and st.overall_stage else []),
        "diagnosis.staging.stage_group": entry([dx.element_id] if st and st.stage_group and st.stage_group != StageGroup.unknown else []),
        "biomarkers": entry([x.element_id for x in b.biomarkers]),
        "performance_status": entry([b.performance_status.element_id] if b.performance_status else []),
        "comorbidities": entry([x.element_id for x in b.comorbidities]),
        "medications.current": entry([x.element_id for x in b.medications if x.intent == MedIntent.current]),
        "medications.proposed": entry([x.element_id for x in b.medications if x.intent == MedIntent.proposed]),
        "labs": entry([x.element_id for x in b.labs]),
        "imaging": entry([x.element_id for x in b.imaging]),
        "prior_treatments": entry([x.element_id for x in b.prior_treatments]),
        "goals_of_care": entry([b.goals_of_care.element_id] if b.goals_of_care else []),
    }


def _build_staleness(b: PatientCaseBundle) -> list[Staleness]:
    out: list[Staleness] = []

    def add(eid: str, selector: str, dated: Optional[str]):
        days = age_days(dated, b.board_date)
        if dated and days is not None:
            out.append(Staleness(element_id=eid, selector=selector, dated_at=dated[:10], age_days=days))

    if b.goals_of_care:
        add(b.goals_of_care.element_id, "goals_of_care", b.goals_of_care.documented_date)
    if b.performance_status:
        add(b.performance_status.element_id, "performance_status", b.performance_status.date)
    if b.diagnosis:
        add(b.diagnosis.element_id, "diagnosis", b.diagnosis.diagnosis_date)
    for x in b.labs:
        add(x.element_id, "labs", x.date)
    for x in b.biomarkers:
        add(x.element_id, "biomarkers", x.date)
    for x in b.imaging:
        add(x.element_id, "imaging", x.date)
    for x in b.prior_treatments:
        add(x.element_id, "prior_treatments", x.date)
    return out



def _goc_covers(goc: dict) -> tuple[list[CareDomain], ScopeSource]:
    """An explicitly coded scope wins; otherwise derive it from the prose. Returns
    (covers, source) — `absent` means the source recorded no scope, which is
    UNKNOWN, not 'covers nothing'."""
    coded = goc.get("covers") or goc.get("scope")
    coded = [coded] if isinstance(coded, str) else coded
    if isinstance(coded, list):
        vals = [CareDomain(c) for c in coded if c in CareDomain._value2member_map_]
        if vals:
            return vals, ScopeSource.coded
    derived = derive_care_domains(goc.get("summary"), goc.get("status"))
    return derived, ScopeSource.derived_from_text if derived else ScopeSource.absent


def to_bundle(record: dict) -> PatientCaseBundle:
    meta = record.get("metadata", {})
    pctx = record.get("patient_context", {})
    fp = pctx.get("patient") or pctx.get("Patient") or {}
    board = meta.get("date") or meta.get("board_date")

    bundle = PatientCaseBundle(
        bundle_version=BUNDLE_VERSION,
        case_id=record.get("id"),
        board_date=board,
        source_digest=source_digest(record),
        patient=Patient(id=fp.get("id"), sex=fp.get("gender"), birth_date=fp.get("birthDate"),
                        age_years=age_years(fp.get("birthDate"), board)),
        longitudinal_summary=_as_str(pctx.get("longitudinal_summary")),
    )
    bld = _Builder(bundle)

    # goals_of_care extension carried outside FHIR resources (contract allows).
    goc = pctx.get("goals_of_care") or record.get("goals_of_care")
    if isinstance(goc, dict):
        eid = bld.eid("goals_of_care", "documented", resource=goc)
        bundle.goals_of_care = GoalsOfCare(
            element_id=eid,
            documented_date=goc.get("last_documented") or goc.get("documented_date"),
            summary=goc.get("summary"), status=goc.get("status"),
            covers=_goc_covers(goc)[0], scope_source=_goc_covers(goc)[1],
            provenance=Provenance(source="patient_context", resource_type="goals_of_care", ref=None, raw_ref=None),
        )

    enc = record.get("encounter_fhir", {})
    groups = enc.get("related_resources", enc)
    if isinstance(groups, dict):
        for rtype, resources in groups.items():
            if rtype == "encounter" or not isinstance(resources, list):
                continue
            handler = _HANDLERS.get(rtype)
            for res in resources:
                if not isinstance(res, dict):
                    continue
                bld.seen_count += 1
                if handler and handler(res, bld):
                    bld.mapped += 1
                else:
                    bundle.unmapped.append(res)
                    bld.warnings.append(f"unmapped resource type: {rtype}")

    bundle.presence = _build_presence(bundle)
    bundle.staleness = _build_staleness(bundle)
    bundle.adapter_report = AdapterReport(
        resources_seen=bld.seen_count, resources_mapped=bld.mapped,
        resources_unmapped=len(bundle.unmapped),
        coverage_ratio=(bld.mapped / bld.seen_count if bld.seen_count else 1.0),
        warnings=bld.warnings,
    )
    return bundle
