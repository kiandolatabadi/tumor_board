"""Normalized tumor-board case schema — the oncology 'essence'.

This is the typed view the board logic reasons over. It is deliberately:
  * extensible — collections are lists of typed records (a new biomarker just
    appends; no schema change), not fixed columns;
  * tolerant — every clinical field is optional, so partial / messy incoming
    data still fits. Absence is not an error; it is a *gap* (see `completeness`);
  * lossless — anything the adapter can't classify is preserved in `unmapped`,
    and every extracted item keeps a `provenance` pointer back to its source.

Incoming data lands as the flexible FHIR envelope; an adapter (see app/ingest)
maps it into this structure. New data sources just need an adapter that emits a
TumorBoardCase — the rest of the pipeline is source-agnostic.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# Shared, dependency-free vocabulary (also re-exported by app/stage2/enums.py).
from .care_domains import CareDomain, ScopeSource, derive_care_domains  # noqa: F401
from .treatment_kinds import TreatmentKind, classify_treatment_kind  # noqa: F401


class Provenance(BaseModel):
    """Where a normalized value came from, so nothing is a black box."""
    source: str = Field(..., description="e.g. 'fhir'.")
    resource_type: Optional[str] = None
    ref: Optional[str] = Field(None, description="resource id or index in the source.")
    raw: Optional[dict] = Field(None, description="the original resource, kept for fallback.")


class TriState(str, Enum):
    positive = "positive"
    negative = "negative"
    equivocal = "equivocal"
    unknown = "unknown"


class BiomarkerCategory(str, Enum):
    mutation = "mutation"
    fusion = "fusion"
    expression = "expression"
    amplification = "amplification"
    signature = "signature"  # MSI, TMB, HRD...
    other = "other"


class Biomarker(BaseModel):
    name: str = Field(..., description="Reported marker name, e.g. 'EGFR exon 19 deletion', 'PD-L1 TPS'.")
    gene: Optional[str] = None
    category: BiomarkerCategory = BiomarkerCategory.other
    status: TriState = TriState.unknown
    value: Optional[str] = Field(None, description="Free-form value/level, e.g. '70%'.")
    method: Optional[str] = None
    date: Optional[str] = None
    provenance: Optional[Provenance] = None


class Staging(BaseModel):
    system: Optional[str] = Field(None, description="e.g. 'AJCC8'.")
    t: Optional[str] = None
    n: Optional[str] = None
    m: Optional[str] = None
    overall_stage: Optional[str] = Field(None, description="e.g. 'IIIA'.")
    grade: Optional[str] = None


class Diagnosis(BaseModel):
    primary_site: Optional[str] = None
    histology: Optional[str] = None
    staging: Optional[Staging] = None
    diagnosis_date: Optional[str] = None
    provenance: Optional[Provenance] = None


class PerformanceStatus(BaseModel):
    scale: Optional[str] = Field(None, description="'ECOG' or 'Karnofsky'.")
    value: Optional[str] = None
    date: Optional[str] = None
    provenance: Optional[Provenance] = None


class Comorbidity(BaseModel):
    name: str
    severity: Optional[str] = None
    provenance: Optional[Provenance] = None


class MedIntent(str, Enum):
    current = "current"
    proposed = "proposed"


class Medication(BaseModel):
    name: str
    intent: MedIntent = MedIntent.current
    reason: Optional[str] = None
    provenance: Optional[Provenance] = None


class LabResult(BaseModel):
    name: str
    value: Optional[str] = None
    unit: Optional[str] = None
    date: Optional[str] = None
    provenance: Optional[Provenance] = None


class ImagingReport(BaseModel):
    modality: Optional[str] = None
    impression: Optional[str] = None
    date: Optional[str] = None
    provenance: Optional[Provenance] = None


class PriorTreatment(BaseModel):
    name: str
    kind: Optional[TreatmentKind] = Field(
        None,
        description="Closed vocabulary — no free strings. Downstream rules match on these values.",
    )
    date: Optional[str] = None
    response: Optional[str] = None
    provenance: Optional[Provenance] = None


class GoalsOfCare(BaseModel):
    documented_date: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    covers: list[CareDomain] = Field(
        default_factory=list,
        description="Care domains this conversation actually addressed. Empty means the source "
        "recorded no scope — NOT that the conversation covered nothing.",
    )
    scope_source: ScopeSource = ScopeSource.absent


class Patient(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    sex: Optional[str] = None
    birth_date: Optional[str] = None


class MissingField(BaseModel):
    field: str
    reason: str


class TumorBoardCase(BaseModel):
    """The normalized oncology case. Everything below the patient is optional."""
    case_id: Optional[str] = None
    board_date: Optional[str] = None
    patient: Patient = Field(default_factory=Patient)
    longitudinal_summary: Optional[str] = None

    diagnosis: Optional[Diagnosis] = None
    biomarkers: list[Biomarker] = Field(default_factory=list)
    performance_status: Optional[PerformanceStatus] = None
    comorbidities: list[Comorbidity] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)
    imaging: list[ImagingReport] = Field(default_factory=list)
    prior_treatments: list[PriorTreatment] = Field(default_factory=list)
    goals_of_care: Optional[GoalsOfCare] = None

    # Lossless catch-all: resources the adapter didn't recognize are kept verbatim.
    unmapped: list[dict[str, Any]] = Field(default_factory=list)

    def completeness(self) -> list[MissingField]:
        """Absent oncology essentials — these are the structural gaps to surface."""
        missing: list[MissingField] = []
        if not (self.diagnosis and self.diagnosis.primary_site):
            missing.append(MissingField(field="diagnosis.primary_site", reason="no primary cancer site identified"))
        if not (self.diagnosis and self.diagnosis.staging and self.diagnosis.staging.overall_stage):
            missing.append(MissingField(field="diagnosis.staging.overall_stage", reason="no overall stage recorded"))
        if not self.biomarkers:
            missing.append(MissingField(field="biomarkers", reason="no molecular/biomarker results present"))
        if not (self.performance_status and self.performance_status.value):
            missing.append(MissingField(field="performance_status", reason="no ECOG/Karnofsky recorded"))
        # goals_of_care absence is NOT flagged here — it is owned by the goals-of-care
        # precondition (app/goc.py, GocStatus.ABSENT), which handles it authoritatively.
        if not any(m.intent == MedIntent.current for m in self.medications):
            missing.append(MissingField(field="medications.current", reason="no current medications listed"))
        return missing
