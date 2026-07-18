"""TranscriptBundle — Stage 2's transcript artifact (contract §4).

Mechanical only: split the transcript into turns, mint stable `line_id`s
(`L{ordinal}`, 1-based position in the file), classify the verbatim speaker
label into a closed `SpeakerRole`, and preserve any timestamp. No clinical
judgment. Stage 3 cites turns by `line_id`.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from pydantic import BaseModel, Field

from .enums import SpeakerRole
from .ids import canonical_json

BUNDLE_VERSION = "1.0.0"

# Optional leading "[HH:MM:SS]", then an ALL-CAPS speaker label, then the text.
_TURN = re.compile(r"^\s*(?:\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*)?([A-Z][A-Z0-9_ ]{1,30}):\s*(.*)$")

# Verbatim label -> role. Order matters: 'pathologist' before 'oncologist',
# 'radiologist' before the generic 'onc' so 'RADIATION ONCOLOGIST' -> oncologist.
_ROLE_KEYWORDS = (
    ("patholog", SpeakerRole.pathologist),
    ("surg", SpeakerRole.surgeon),
    ("nurse", SpeakerRole.nurse_coordinator),
    ("coordinator", SpeakerRole.nurse_coordinator),
    ("radiolog", SpeakerRole.radiologist),
    ("oncolog", SpeakerRole.oncologist),
    ("onc", SpeakerRole.oncologist),
)


def classify_speaker_role(speaker: str) -> SpeakerRole:
    low = (speaker or "").lower()
    for kw, role in _ROLE_KEYWORDS:
        if kw in low:
            return role
    return SpeakerRole.other


class Turn(BaseModel):
    line_id: str = Field(..., description="Stable citation id, 'L{ordinal}'.")
    ordinal: int = Field(..., description="1-based position in the transcript file.")
    speaker: str = Field(..., description="Verbatim speaker label, e.g. 'ONCOLOGIST'.")
    speaker_role: SpeakerRole
    text: str
    timestamp: Optional[str] = Field(None, description="HH:MM:SS if present.")


class TranscriptBundle(BaseModel):
    bundle_version: str = BUNDLE_VERSION
    transcript_id: str
    source_digest: str
    turns: list[Turn] = Field(default_factory=list)


def _digest(transcript: str | list) -> str:
    blob = transcript if isinstance(transcript, str) else canonical_json(transcript)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _raw_turns(transcript: str | list) -> list[tuple[Optional[str], str, str]]:
    """(timestamp, speaker, text) triples. A line without a speaker label is a
    continuation of the previous turn."""
    if isinstance(transcript, list):
        return [
            (t.get("timestamp"), t.get("speaker") or "UNKNOWN", t.get("text", ""))
            for t in transcript
        ]
    raw: list[list] = []
    for line in (transcript or "").splitlines():
        if not line.strip():
            continue
        m = _TURN.match(line)
        if m:
            raw.append([m.group(1), m.group(2).strip(), m.group(3).strip()])
        elif raw:  # continuation of the prior speaker's turn
            raw[-1][2] = f"{raw[-1][2]} {line.strip()}".strip()
        # leading text with no speaker label is dropped (not a turn)
    return [(ts, spk, txt) for ts, spk, txt in raw]


def to_transcript_bundle(transcript: str | list, transcript_id: str) -> TranscriptBundle:
    """Build a TranscriptBundle from a transcript string or a list of turns.
    `transcript_id` is the partition key (the patient folder name when loaded
    per-folder), so one patient's turns can never be cited as another's."""
    turns = [
        Turn(
            line_id=f"L{i:03d}",
            ordinal=i,
            speaker=speaker,
            speaker_role=classify_speaker_role(speaker),
            text=text,
            timestamp=ts,
        )
        for i, (ts, speaker, text) in enumerate(_raw_turns(transcript), start=1)
    ]
    return TranscriptBundle(transcript_id=transcript_id, source_digest=_digest(transcript), turns=turns)
