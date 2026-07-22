"""A minimal FastAPI app exposing the panel — self-contained, no legacy imports.

    uvicorn app.panel.api:app --reload   (from backend/)

Endpoints:
    GET  /health
    GET  /cases                  → identity list (from the clean folders)
    GET  /cases/{case_id}        → one case's documents + transcript
    POST /board  {case_id}       → run the panel, return the board output
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..cases import CaseDetail, CaseSummary, get_case, list_cases
from ..config import FRONTEND_ORIGIN
from .llm import CallBudgetExceeded
from .orchestrator import run_board
from .schema import PanelResult

app = FastAPI(title="Tumor Board Panel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


class BoardRequest(BaseModel):
    case_id: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/cases", response_model=list[CaseSummary])
def all_cases() -> list[CaseSummary]:
    return list_cases()


@app.get("/cases/{case_id}", response_model=CaseDetail)
def one_case(case_id: str) -> CaseDetail:
    case = get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_id}")
    return case


@app.post("/board", response_model=PanelResult)
def board(req: BoardRequest) -> PanelResult:
    try:
        return run_board(req.case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown case: {req.case_id}")
    except CallBudgetExceeded as e:
        # A runaway was stopped by the budget — report it plainly, don't 500.
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        if "ANTHROPIC_API_KEY" in str(e):
            raise HTTPException(status_code=400, detail=str(e).splitlines()[0])
        raise
