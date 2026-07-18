"""Treatment-kind vocabulary and its classifier.

Dependency-free, like `app/care_domains.py`: both the Stage 2 contract
(`app/stage2/`) and the pre-split adapter (`app/ingest/fhir_adapter.py`) import
from here, so the vocabulary has exactly one definition and the two layers cannot
drift apart.

The drift this exists to prevent was real: `fhir_adapter` hardcoded
`kind="procedure"` while the schema documented `'surgery' | 'systemic' |
'radiation'`, so a downstream rule matching `kind == "surgery"` matched nothing,
forever, with no error.
"""
from __future__ import annotations

from enum import Enum


class TreatmentKind(str, Enum):
    surgery = "surgery"
    systemic = "systemic"
    radiation = "radiation"
    ablation = "ablation"
    transplant = "transplant"
    other = "other"


_PATTERNS = (
    (("resect", "ectomy", "surgery", "surgical"), TreatmentKind.surgery),
    (("radiation", "radiotherapy", "brachytherapy"), TreatmentKind.radiation),
    (("chemo", "systemic", "infusion", "immunotherapy"), TreatmentKind.systemic),
    (("ablat",), TreatmentKind.ablation),
    (("transplant",), TreatmentKind.transplant),
)


def classify_treatment_kind(label: str) -> TreatmentKind:
    """Keyword classification into the closed vocabulary. Unrecognized labels fall
    to `other` — which callers must still treat as a real clinical event, not as
    'nothing happened'."""
    low = (label or "").lower()
    for keys, kind in _PATTERNS:
        if any(k in low for k in keys):
            return kind
    return TreatmentKind.other
