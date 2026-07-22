"""Turn a clean on-disk case folder into the text the panel reasons over.

This is the whole ingestion story now: read the markdown the physician authored
(``cases.get_case`` — folders of notes + the board transcript) and lay it out as
one readable brief. No FHIR, no normalized case object, no extraction schema —
the model reads the chart the way a clinician does.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..cases import CaseDetail, get_case


@dataclass(frozen=True)
class BoardContext:
    case_id: str
    identity: str          # one-line patient identity
    chart: str             # every chart document, rendered
    transcript: str        # the board discussion, verbatim

    def brief(self) -> str:
        """The full case brief handed to every specialist."""
        return (
            f"PATIENT: {self.identity}\n\n"
            f"=== CHART (documents authored by the care team, newest first per folder) ===\n"
            f"{self.chart}\n\n"
            f"=== TUMOR BOARD TRANSCRIPT (what the room actually discussed) ===\n"
            f"{self.transcript or '(no transcript on file)'}\n"
        )


def _render_chart(detail: CaseDetail) -> str:
    blocks: list[str] = []
    for folder in detail.folders:
        for doc in folder.documents:
            dated = f" — {doc.date}" if doc.date else ""
            blocks.append(
                f"----- [{folder.label}] {doc.title}{dated} (doc_id: {doc.doc_id}) -----\n"
                f"{doc.body.strip()}"
            )
    return "\n\n".join(blocks)


def _identity(detail: CaseDetail) -> str:
    parts = [
        detail.patient_ref,
        detail.cancer_type and f"{detail.cancer_type} cancer",
        detail.line_of_therapy,
        detail.board_date and f"board date {detail.board_date}",
    ]
    return " · ".join(p for p in parts if p) or detail.case_id


def load_context(case_id: str) -> BoardContext:
    """Build the reasoning context for a case, or raise KeyError if unknown."""
    detail = get_case(case_id)
    if detail is None:
        raise KeyError(case_id)
    return BoardContext(
        case_id=detail.case_id,
        identity=_identity(detail),
        chart=_render_chart(detail),
        transcript=detail.transcript or "",
    )
