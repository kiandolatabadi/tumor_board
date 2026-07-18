"""PatientCaseBundle — Stage 2's output (contract §2).

Mechanical facts only. Every clinical collection record carries an `element_id`
(stable citation target) and `provenance`. Raw source resources are NOT inlined;
`provenance.raw_ref` points into the `raw_resources` side-car so the bulk is
optional downstream. The word "gap" appears nowhere here by design.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import (BiomarkerCategory, CareDomain, MedIntent, PerfScale, ScopeSource, StageGroup,
                    TreatmentKind, TriState)

BUNDLE_VERSION = "1.0.0"


class Provenance(BaseModel):
    source: str = Field(..., description="e.g. 'fhir'.")
    resource_type: Optional[str] = None
    ref: Optional[str] = Field(None, description="Source resource id when present; NEVER an array index.")
    raw_ref: Optional[str] = Field(None, description="Pointer into bundle.raw_resources.")


class Patient(BaseModel):
    id: Optional[str] = None
    sex: Optional[str] = None
    birth_date: Optional[str] = None
    age_years: Optional[int] = Field(None, description="Computed at board_date; deterministic.")
    # `name` deliberately excluded — Stage 3 never needs it.


class Staging(BaseModel):
    system: Optional[str] = None
    t: Optional[str] = None
    n: Optional[str] = None
    m: Optional[str] = None
    overall_stage: Optional[str] = None
    stage_group: Optional[StageGroup] = Field(None, description="Coarse bucket for guidance matching.")
    grade: Optional[str] = None


class Diagnosis(BaseModel):
    element_id: str
    primary_site: Optional[str] = None
    histology: Optional[str] = None
    diagnosis_date: Optional[str] = None
    staging: Optional[Staging] = None
    provenance: Provenance


class Biomarker(BaseModel):
    element_id: str
    name: str
    gene: Optional[str] = None
    category: BiomarkerCategory = BiomarkerCategory.other
    status: TriState = TriState.unknown
    value: Optional[str] = None
    value_num: Optional[float] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    date: Optional[str] = None
    provenance: Provenance


class PerformanceStatus(BaseModel):
    element_id: str
    scale: Optional[PerfScale] = None
    value: Optional[str] = None
    value_num: Optional[float] = None
    date: Optional[str] = None
    provenance: Provenance


class Comorbidity(BaseModel):
    element_id: str
    name: str
    severity: Optional[str] = None
    provenance: Provenance


class Medication(BaseModel):
    element_id: str
    name: str
    intent: MedIntent = MedIntent.current
    reason: Optional[str] = None
    provenance: Provenance


class LabResult(BaseModel):
    element_id: str
    name: str
    value: Optional[str] = None
    value_num: Optional[float] = None
    unit: Optional[str] = None
    date: Optional[str] = None
    provenance: Provenance


class ImagingReport(BaseModel):
    element_id: str
    modality: Optional[str] = None
    impression: Optional[str] = None
    date: Optional[str] = None
    provenance: Provenance


class PriorTreatment(BaseModel):
    element_id: str
    name: str
    kind: TreatmentKind = Field(..., description="Closed enum — no free strings.")
    date: Optional[str] = None
    response: Optional[str] = None
    provenance: Provenance


class GoalsOfCare(BaseModel):
    element_id: str
    documented_date: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    # Which care domains the conversation ADDRESSED. Mechanical: Stage 2 records
    # what a document covers; whether that answers a given clinical question is
    # Stage 3's join. `scope_source == absent` means UNKNOWN, not "covers nothing" —
    # do not read an empty list as absence of coverage.
    covers: list[CareDomain] = Field(default_factory=list)
    scope_source: ScopeSource = ScopeSource.absent
    provenance: Provenance


class PresenceEntry(BaseModel):
    present: bool
    element_ids: list[str] = Field(default_factory=list, description="Empty when present=false.")
    count: int = 0


class Staleness(BaseModel):
    """Raw date arithmetic only — NO threshold. What is 'too old' is Stage 3's call."""
    element_id: str
    selector: str
    dated_at: str
    age_days: int


class AdapterReport(BaseModel):
    resources_seen: int = 0
    resources_mapped: int = 0
    resources_unmapped: int = 0
    coverage_ratio: float = 1.0
    warnings: list[str] = Field(default_factory=list)


# The mechanical selectors Stage 2 must always report (present or not) — contract §2.
REQUIRED_SELECTORS = (
    "diagnosis.primary_site",
    "diagnosis.histology",
    "diagnosis.staging.overall_stage",
    "diagnosis.staging.stage_group",
    "biomarkers",
    "performance_status",
    "comorbidities",
    "medications.current",
    "medications.proposed",
    "labs",
    "imaging",
    "prior_treatments",
    "goals_of_care",
)


class PatientCaseBundle(BaseModel):
    bundle_version: str = BUNDLE_VERSION
    case_id: Optional[str] = None
    board_date: Optional[str] = Field(None, description="Reference date for ALL date arithmetic.")
    source_digest: str

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

    unmapped: list[dict] = Field(default_factory=list)

    presence: dict[str, PresenceEntry] = Field(default_factory=dict)
    staleness: list[Staleness] = Field(default_factory=list)
    adapter_report: AdapterReport = Field(default_factory=AdapterReport)

    # Side-car: provenance.raw_ref -> original resource. Droppable from model context.
    raw_resources: dict[str, dict] = Field(default_factory=dict)
