"""TranscriptBundle — contract §4 shape + speaker-role classification (no API key)."""
import json
import pathlib

import pytest
import yaml

from app.stage2 import load_patient, load_transcript_bundle, to_transcript_bundle
from app.stage2.enums import SpeakerRole
from app.stage2.transcript import classify_speaker_role

ROOT = pathlib.Path(__file__).parents[2]
FX = ROOT / "fixtures" / "contract" / "v1"
PATIENTS = ROOT / "fixtures" / "patients"
CONTRACT = yaml.safe_load((ROOT / "docs" / "stage-interface-contract.yaml").read_text())
SOURCE = json.loads((FX / "source_record.json").read_text())


def test_speaker_role_enum_matches_contract():
    assert {r.value for r in SpeakerRole} == set(CONTRACT["enumerations"]["SPEAKER_ROLE"])


def test_line_ids_are_sequential_and_1_based():
    tb = to_transcript_bundle(SOURCE["transcript"], transcript_id="t1")
    assert [t.line_id for t in tb.turns] == [f"L{i:03d}" for i in range(1, len(tb.turns) + 1)]
    assert [t.ordinal for t in tb.turns] == list(range(1, len(tb.turns) + 1))
    assert tb.turns[0].line_id == "L001"


@pytest.mark.parametrize("label,role", [
    ("ONCOLOGIST", SpeakerRole.oncologist),
    ("RADIOLOGIST", SpeakerRole.radiologist),
    ("SURGEON", SpeakerRole.surgeon),
    ("PATHOLOGIST", SpeakerRole.pathologist),
    ("NURSE_COORDINATOR", SpeakerRole.nurse_coordinator),
    ("RADIATION ONCOLOGIST", SpeakerRole.oncologist),  # 'radiolog' != 'radiat'; falls to oncologist
    ("SOCIAL WORKER", SpeakerRole.other),
])
def test_speaker_role_classification(label, role):
    assert classify_speaker_role(label) == role


def test_verbatim_speaker_is_preserved():
    tb = to_transcript_bundle("NURSE_COORDINATOR: I'll schedule it.", transcript_id="t1")
    assert tb.turns[0].speaker == "NURSE_COORDINATOR"          # verbatim
    assert tb.turns[0].speaker_role == SpeakerRole.nurse_coordinator


def test_continuation_line_appends_to_prior_turn():
    tb = to_transcript_bundle("ONCOLOGIST: first part\nsecond part here.\nSURGEON: my turn.", transcript_id="t1")
    assert len(tb.turns) == 2
    assert "second part here" in tb.turns[0].text
    assert tb.turns[1].speaker == "SURGEON"


def test_timestamp_is_captured():
    tb = to_transcript_bundle("[00:14:32] SURGEON: lobectomy is on the table.", transcript_id="t1")
    assert tb.turns[0].timestamp == "00:14:32"


def test_list_form_transcript_is_accepted():
    turns = [{"speaker": "ONCOLOGIST", "text": "a", "timestamp": "00:00:01"},
             {"speaker": "SURGEON", "text": "b", "timestamp": None}]
    tb = to_transcript_bundle(turns, transcript_id="t1")
    assert [t.speaker for t in tb.turns] == ["ONCOLOGIST", "SURGEON"]
    assert tb.turns[0].timestamp == "00:00:01"


def test_adapter_matches_golden_transcript_bundle():
    golden = json.loads((FX / "transcript_bundle.json").read_text())
    assert to_transcript_bundle(SOURCE["transcript"], transcript_id=SOURCE["id"]).model_dump(mode="json") == golden


def test_transcript_bundle_is_folder_isolated():
    """transcript_id is the folder name; turns come only from that folder."""
    tb = load_transcript_bundle(PATIENTS / "patient-001")
    assert tb.transcript_id == "patient-001"
    assert len(tb.turns) == 2  # patient-001's transcript.txt has two turns
    assert tb.turns[0].speaker == "ONCOLOGIST"
    # patient-002 has no transcript file -> empty, not patient-001's turns
    tb2 = load_transcript_bundle(PATIENTS / "patient-002")
    assert tb2.transcript_id == "patient-002" and tb2.turns == []


def test_load_patient_returns_both_bundles_same_key():
    bundle, tb = load_patient(PATIENTS / "patient-001")
    assert bundle.case_id == tb.transcript_id == "patient-001"
