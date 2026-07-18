"""Stage 2 — patient data structuring (contract: docs/stage-interface-contract.yaml).

Raw FHIR-shaped source record → PatientCaseBundle: normalized, addressable,
provenance-carrying facts plus mechanical presence/staleness. No clinical
judgment; the word "gap" never appears here. See `to_bundle`.
"""
from .adapter import to_bundle
from .bundle import PatientCaseBundle
from .loader import (
    MixedPatientDataError,
    discover_patients,
    load_all,
    load_patient,
    load_patient_folder,
    load_transcript_bundle,
)
from .transcript import TranscriptBundle, to_transcript_bundle

__all__ = [
    "to_bundle",
    "PatientCaseBundle",
    "TranscriptBundle",
    "to_transcript_bundle",
    "load_patient_folder",
    "load_transcript_bundle",
    "load_patient",
    "load_all",
    "discover_patients",
    "MixedPatientDataError",
]
