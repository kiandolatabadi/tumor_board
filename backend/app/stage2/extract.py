"""Stage 2 extractor for the on-disk case format (`data/cases/<case>/`).

Consumes the case repository (`app.cases.get_case`) — which reads the specialty
markdown notes and strips the benchmark answer key — and turns the *mechanically
structured* parts (tables, labeled `**Field:**` lines) into a PatientCaseBundle +
TranscriptBundle. Prose (histories, radiology findings, comorbidity narratives) is
deliberately NOT interpreted here; it stays on disk for the enrichment layer.

Reuses the FHIR-envelope `to_bundle` pipeline: each specialty handler emits FHIR
resources, then to_bundle does the element_ids / presence / staleness. One case
folder in, one bundle out (isolation is inherited from get_case reading one case).
"""
from __future__ import annotations

import re
from typing import Optional

from ..cases import CaseDetail, get_case
from .bundle import PatientCaseBundle
from .adapter import to_bundle
from .markdown import find_table, get_cell, inline_fields
from .transcript import TranscriptBundle, to_transcript_bundle

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SYN_MRN = re.compile(r"\bSYN-[A-Z]{2}-\d+\b")


def _first_date(text: str) -> Optional[str]:
    m = _ISO_DATE.search(text or "")
    return m.group(0) if m else None


class _Extractor:
    """Accumulates FHIR resources from one case's documents."""

    def __init__(self, case: CaseDetail):
        self.case = case
        self.rr: dict[str, list[dict]] = {}          # related_resources by type
        self.patient: dict = {}
        self.goals: Optional[dict] = None
        self.diagnosis_text: Optional[str] = None    # from pathology
        self.staging: Optional[str] = None           # from oncology

    def add(self, rtype: str, resource: dict) -> None:
        self.rr.setdefault(rtype, []).append(resource)

    # --- specialty handlers -------------------------------------------------
    def _biometrics(self, doc) -> None:
        f = inline_fields(doc.body)
        if not self.patient:
            mrn = _SYN_MRN.search(doc.body)
            self.patient = {
                "resourceType": "Patient",
                "id": mrn.group(0) if mrn else None,
                "name": f.get("patient"),
                "gender": (f.get("sex") or "").lower() or None,
                "birthDate": _first_date(f.get("dob", "")),
            }
        # ECOG from the vitals table (latest dated row).
        vitals = find_table(doc.body, "Date", "ECOG")
        dated = [r for r in vitals if get_cell(r, "ECOG") not in (None, "")]
        if dated:
            latest = max(dated, key=lambda r: get_cell(r, "Date") or "")
            self.add("Observation", {
                "resourceType": "Observation", "code": "ECOG performance status",
                "value": get_cell(latest, "ECOG"), "effectiveDateTime": get_cell(latest, "Date"),
            })

    def _pathology(self, doc) -> None:
        table = find_table(doc.body, "Marker", "Result")
        for row in table:
            marker, result = get_cell(row, "Marker"), get_cell(row, "Result")
            if marker and result:
                self.add("Observation", {
                    "resourceType": "Observation", "code": marker,
                    "value": result, "effectiveDateTime": doc.date,
                })
        dx = inline_fields(doc.body).get("diagnosis")
        if dx and not self.diagnosis_text:
            self.diagnosis_text = dx

    def _laboratory(self, doc) -> None:
        table = find_table(doc.body, "Test", "Result")
        for row in table:
            test, result = get_cell(row, "Test"), get_cell(row, "Result")
            if test and result:
                self.add("Observation", {
                    "resourceType": "Observation", "code": test, "value": result,
                    "effectiveDateTime": doc.date,
                })

    def _medications(self, doc) -> None:
        table = find_table(doc.body, "Medication")
        for row in table:
            name = get_cell(row, "Medication")
            if name:
                self.add("MedicationRequest", {
                    "resourceType": "MedicationRequest", "medication": name,
                    "intent": "order", "reason": get_cell(row, "Indication"),
                })

    def _oncology(self, doc) -> None:
        f = inline_fields(doc.body)
        if f.get("staging") and not self.staging:
            self.staging = f["staging"]
        goc = f.get("goals of care")
        if goc and not self.goals:
            self.goals = {"last_documented": doc.date, "summary": goc, "status": None}

    def _radiology(self, doc) -> None:
        impression = inline_fields(doc.body).get("impression")
        if impression:
            self.add("DiagnosticReport", {
                "resourceType": "DiagnosticReport", "code": doc.title or "Imaging",
                "conclusion": impression, "effectiveDateTime": doc.date,
            })

    def _pneumology(self, doc) -> None:
        table = find_table(doc.body, "Measure", "Result")
        for row in table:
            measure, result = get_cell(row, "Measure"), get_cell(row, "Result")
            if measure and result:
                self.add("Observation", {
                    "resourceType": "Observation", "code": measure, "value": result,
                    "effectiveDateTime": doc.date,
                })

    _HANDLERS = {
        "biometrics": _biometrics,
        "pathology": _pathology,
        "laboratory": _laboratory,
        "medications": _medications,
        "oncology": _oncology,
        "radiology": _radiology,
        "pneumology": _pneumology,
    }

    def build_record(self) -> dict:
        for folder in self.case.folders:
            handler = self._HANDLERS.get(folder.name)
            if not handler:
                continue
            for doc in folder.documents:
                handler(self, doc)

        # One diagnosis Condition, assembled after all notes so order doesn't matter:
        # the pathology diagnosis line (most specific) with the oncology staging.
        code = self.diagnosis_text or (f"{self.case.cancer_type} cancer" if self.case.cancer_type else None)
        if code:
            cond = {"resourceType": "Condition", "code": code}
            if self.staging:
                cond["stage"] = self.staging
            self.add("Condition", cond)

        pctx: dict = {"patient": self.patient}
        if self.goals:
            pctx["goals_of_care"] = self.goals
        return {
            "id": self.case.case_id,
            "metadata": {"date": self.case.board_date},
            "patient_context": pctx,
            "encounter_fhir": {"related_resources": self.rr},
            "transcript": self.case.transcript or "",
        }


def bundle_from_case(case: CaseDetail) -> tuple[PatientCaseBundle, TranscriptBundle]:
    """Both Stage 2 artifacts for one case. Deterministic — no model calls."""
    record = _Extractor(case).build_record()
    bundle = to_bundle(record)
    bundle.case_id = case.case_id  # partition key
    transcript = to_transcript_bundle(case.transcript or "", transcript_id=case.case_id)
    return bundle, transcript


def load_case_bundle(case_id: str) -> tuple[PatientCaseBundle, TranscriptBundle]:
    """Look up a case in the repository and structure it. Raises KeyError if unknown."""
    case = get_case(case_id)
    if case is None:
        raise KeyError(f"unknown case: {case_id}")
    return bundle_from_case(case)


# Prose-heavy specialties worth an enrichment read. The table-heavy folders
# (laboratory, medications, pathology panels) are already extracted deterministically,
# so feeding them to the LLM is cost without nuance.
_PROSE_FOLDERS = {"oncology", "radiology", "biometrics", "gynecology", "pneumology"}


def _case_free_text(case: CaseDetail) -> dict[str, str]:
    """The prose the enrichment layer reads — the narrative documents, keyed by doc id.
    Stage 2 doesn't interpret these; enrichment grounds its inferences against them."""
    return {
        f"{f.name}/{d.filename}": d.body
        for f in case.folders if f.name in _PROSE_FOLDERS
        for d in f.documents
    }


def analysis_inputs_from_case(case_id: str) -> tuple[dict, dict]:
    """Everything the existing orchestrator pipeline needs for one case: the
    FHIR-envelope record (feeds ingest + transcript parsing) and the prose free-text
    (feeds enrichment). Raises KeyError if the case is unknown."""
    case = get_case(case_id)
    if case is None:
        raise KeyError(f"unknown case: {case_id}")
    return _Extractor(case).build_record(), _case_free_text(case)
