"""Case repository + patient-browser endpoints.

The load-bearing test here is the answer-key one: case_meta.json carries the
benchmark ground truth (planted_gaps and friends), and serving it to a clinical
view would both spoil the demo and show a clinician "findings" the system never
actually derived.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.cases import get_case, list_cases
from app.main import app

client = TestClient(app)
HERO = "hero_breast_escalation"


def test_cases_are_discovered_from_disk():
    ids = {c.case_id for c in list_cases()}
    assert HERO in ids
    assert len(ids) >= 5


def test_case_detail_exposes_folders_and_transcript():
    d = get_case(HERO)
    assert d is not None
    assert [f.name for f in d.folders]
    assert d.transcript and "ONCOLOGIST" in d.transcript  # a real board transcript with turns
    assert d.document_count == sum(len(f.documents) for f in d.folders)


def test_answer_key_never_leaves_the_repository():
    """planted_gaps / expected_findings_count / noise_documents are ground truth."""
    body = client.get(f"/cases/{HERO}").text
    for leaked in ("planted_gaps", "expected_findings_count",
                   "noise_documents_not_expected_to_fire", "catching_check"):
        assert leaked not in body, f"benchmark ground truth leaked: {leaked}"


def test_folders_are_discovered_not_assumed():
    """Cases carry different specialties — the API reports what exists."""
    lung = get_case("variant_4_lung_control")
    breast = get_case(HERO)
    assert "pneumology" in {f.name for f in lung.folders}
    assert "pneumology" not in {f.name for f in breast.folders}


def test_folder_order_is_stable_between_list_and_detail():
    """The tab strip is built from either shape; they must not disagree."""
    summary = next(c for c in list_cases() if c.case_id == HERO)
    assert summary.folder_names == [f.name for f in get_case(HERO).folders]


def test_unlisted_specialty_still_appears():
    """A folder outside the preferred order is appended, never dropped."""
    lung = get_case("variant_4_lung_control")
    assert lung.folders[-1].name == "pneumology"


def test_documents_sort_standing_first_then_newest():
    meds = next(f for f in get_case(HERO).folders if f.name == "medications")
    assert meds.documents[0].date is None          # the current med list is standing
    dated = [d.date for d in meds.documents if d.date]
    assert dated == sorted(dated, reverse=True)


def test_document_title_comes_from_the_h1():
    labs = next(f for f in get_case(HERO).folders if f.name == "laboratory")
    assert labs.documents[0].title.startswith("Laboratory Report")
    assert "--" not in labs.documents[0].title       # normalized to an em dash


def test_unknown_case_is_404():
    assert client.get("/cases/nope").status_code == 404


def test_case_list_endpoint_shape():
    rows = client.get("/cases").json()
    assert rows and {"case_id", "folder_names", "document_count"} <= set(rows[0])
