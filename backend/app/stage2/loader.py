"""Per-patient folder loader — patient-data isolation, by construction.

Convention: each immediate subfolder of the data directory is ONE patient's data
set (multiple files per folder). Reference datasets (e.g. `abridge/`) are reserved
and skipped.

    data/
      patient-001/   <- one patient: FHIR resource files + a transcript, etc.
      patient-002/   <- a different patient
      abridge/       <- reserved reference dataset (not a single patient)

Isolation guarantees (all enforced here, tested in test_stage2_loader.py):
  1. One folder -> one PatientCaseBundle. `load_patient_folder` reads ONLY files
     inside the folder it is given; there is no code path that reads across
     sibling folders, so a new folder cannot bleed into an existing patient.
  2. Identity-consistency guard. If the files in a folder disagree on WHO the
     patient is (a stray file from another patient), it RAISES
     `MixedPatientDataError` instead of silently merging a Frankenpatient.
  3. The folder name is the partition key: `bundle.case_id` is set to the folder
     name, so two patients can never be confused downstream even if their internal
     element_ids coincide.
  4. Per-patient failure isolation. `load_all` captures a bad folder's error
     against that patient only; the rest of the demo set still loads.

Adding demo data later needs no code change: drop a new folder in, and it is
discovered and loaded in isolation at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .adapter import to_bundle
from .bundle import PatientCaseBundle
from .transcript import TranscriptBundle, to_transcript_bundle

# stage2 -> app -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Subfolders of the data dir that are NOT a single patient.
RESERVED_DIRS = {"abridge"}

_TEXT_SUFFIXES = {".txt", ".md"}


class MixedPatientDataError(Exception):
    """Raised when one patient folder contains data for more than one patient."""


def discover_patients(data_dir: Path | str = DEFAULT_DATA_DIR, reserved=RESERVED_DIRS) -> list[Path]:
    """List patient folders (runtime discovery — no hardcoded roster). Reserved
    and hidden directories are skipped."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return []
    return sorted(
        p for p in data_dir.iterdir()
        if p.is_dir() and p.name not in reserved and not p.name.startswith(".")
    )


def _patient_ref(resource: dict) -> Optional[str]:
    """The patient a FHIR resource belongs to, from subject/patient reference."""
    for key in ("subject", "patient"):
        ref = resource.get(key)
        if isinstance(ref, dict):
            r = ref.get("reference")
            if isinstance(r, str) and r:
                return r.split("/")[-1]
        elif isinstance(ref, str) and ref.startswith("Patient/"):
            return ref.split("/")[-1]
    return None


class _Assembler:
    """Merges the files of ONE folder into a single FHIR-envelope record."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.record: dict = {
            "id": folder.name,
            "metadata": {},
            "patient_context": {},
            "encounter_fhir": {"related_resources": {}},
            "transcript": "",
        }
        self._transcript: list[str] = []
        self.warnings: list[str] = []

    # --- resource routing ---------------------------------------------------
    def _add_resource(self, res: dict) -> None:
        if not isinstance(res, dict):
            return
        rt = res.get("resourceType")
        if rt == "Patient":
            self.record["patient_context"]["patient"] = res
        elif rt:
            self.record["encounter_fhir"]["related_resources"].setdefault(rt, []).append(res)
        else:
            self.warnings.append("resource without resourceType ignored")

    def _merge_envelope(self, data: dict) -> None:
        pctx = data.get("patient_context", {})
        if pctx.get("patient"):
            self.record["patient_context"]["patient"] = pctx["patient"]
        if pctx.get("longitudinal_summary"):
            self.record["patient_context"]["longitudinal_summary"] = pctx["longitudinal_summary"]
        if pctx.get("goals_of_care") or data.get("goals_of_care"):
            self.record["patient_context"]["goals_of_care"] = pctx.get("goals_of_care") or data.get("goals_of_care")
        self.record["metadata"].update(data.get("metadata", {}))
        rr = data.get("encounter_fhir", {}).get("related_resources", {})
        for rtype, resources in (rr.items() if isinstance(rr, dict) else []):
            for res in (resources if isinstance(resources, list) else []):
                self._add_resource(res)
        if data.get("transcript"):
            self._transcript.append(data["transcript"] if isinstance(data["transcript"], str) else json.dumps(data["transcript"]))

    def _consume_json(self, name: str, data) -> None:
        if isinstance(data, str):
            self._transcript.append(data)
        elif isinstance(data, list):
            for res in data:
                self._add_resource(res)
        elif isinstance(data, dict):
            if "patient_context" in data or "encounter_fhir" in data:
                self._merge_envelope(data)
            elif data.get("resourceType") == "Bundle":
                for entry in data.get("entry", []):
                    if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
                        self._add_resource(entry["resource"])
            elif data.get("resourceType"):
                self._add_resource(data)
            elif "transcript" in data:
                t = data["transcript"]
                self._transcript.append(t if isinstance(t, str) else json.dumps(t))
            elif "goals_of_care" in data:
                self.record["patient_context"]["goals_of_care"] = data["goals_of_care"]
            elif "metadata" in name or name == "metadata.json":
                self.record["metadata"].update(data)
            else:
                self.warnings.append(f"unrecognized json file: {name}")

    def assemble(self) -> dict:
        for path in sorted(self.folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            suffix = path.suffix.lower()
            if suffix in _TEXT_SUFFIXES:
                self._transcript.append(path.read_text(encoding="utf-8"))
            elif suffix == ".json":
                # A broken clinical file must fail loudly, not be silently skipped.
                data = json.loads(path.read_text(encoding="utf-8"))
                self._consume_json(path.name.lower(), data)
            else:
                self.warnings.append(f"ignored non-data file: {path.name}")
        self.record["transcript"] = "\n".join(t.strip() for t in self._transcript if t.strip())
        return self.record

    def identities(self) -> set[str]:
        ids: set[str] = set()
        patient = self.record["patient_context"].get("patient")
        if isinstance(patient, dict) and patient.get("id"):
            ids.add(patient["id"])
        for resources in self.record["encounter_fhir"]["related_resources"].values():
            for res in resources:
                ref = _patient_ref(res)
                if ref:
                    ids.add(ref)
        return ids


def _assemble_isolated(folder: Path | str) -> tuple[Path, dict, list[str]]:
    """Assemble ONE folder's files into one record, enforcing single-patient
    identity. Shared by every per-folder loader so the isolation guard runs once
    and identically for the case bundle and the transcript bundle."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"not a patient folder: {folder}")
    asm = _Assembler(folder)
    record = asm.assemble()
    ids = asm.identities()
    if len(ids) > 1:
        raise MixedPatientDataError(
            f"folder '{folder.name}' contains data for multiple patients: {sorted(ids)}. "
            "Each folder must hold exactly one patient."
        )
    return folder, record, asm.warnings


def load_patient_folder(folder: Path | str) -> PatientCaseBundle:
    """Assemble one folder's files into one PatientCaseBundle, in isolation.

    Raises MixedPatientDataError if the folder's files reference more than one
    patient. The returned bundle's case_id IS the folder name (the partition key).
    """
    folder, record, warnings = _assemble_isolated(folder)
    bundle = to_bundle(record)
    bundle.case_id = folder.name  # authoritative partition key — never the file's internal id
    bundle.adapter_report.warnings.extend(warnings)
    return bundle


def load_transcript_bundle(folder: Path | str) -> TranscriptBundle:
    """Build the TranscriptBundle for one patient folder, in isolation.
    transcript_id is the folder name, so turns can't be cited across patients."""
    folder, record, _ = _assemble_isolated(folder)
    return to_transcript_bundle(record.get("transcript", ""), transcript_id=folder.name)


def load_patient(folder: Path | str) -> tuple[PatientCaseBundle, TranscriptBundle]:
    """Both Stage 2 artifacts for one patient folder, from a single isolated
    assembly (the identity guard runs once). Both share the folder-name key."""
    folder, record, warnings = _assemble_isolated(folder)
    bundle = to_bundle(record)
    bundle.case_id = folder.name
    bundle.adapter_report.warnings.extend(warnings)
    transcript = to_transcript_bundle(record.get("transcript", ""), transcript_id=folder.name)
    return bundle, transcript


def load_all(data_dir: Path | str = DEFAULT_DATA_DIR) -> tuple[dict[str, PatientCaseBundle], dict[str, str]]:
    """Load every patient folder independently. A failing folder is captured as an
    error for THAT patient only — one bad folder never breaks the rest."""
    bundles: dict[str, PatientCaseBundle] = {}
    errors: dict[str, str] = {}
    for folder in discover_patients(data_dir):
        try:
            bundles[folder.name] = load_patient_folder(folder)
        except Exception as e:  # per-patient isolation of failures
            errors[folder.name] = f"{type(e).__name__}: {e}"
    return bundles, errors
