# Panel architecture (the agentic rebuild)

The `backend/app/panel/` package replaces the legacy analysis core. It is
**format-free and agentic**: it reasons over the clean Markdown a clinician
authors (`data/cases/<case_id>/`), with LLM specialists doing the clinical work
and code enforcing only the hard safety rules.

## Why the rebuild

The legacy path (`orchestrator.py`, `stage2/`, `ingest/fhir_adapter.py`, the
canned-table `tools/`) modeled a FHIR-ish data format this project doesn't have,
and hard-coded the clinical logic that should be the model's job:

- `_sweep_tools` ran *every* check on *every* case and explicitly disabled the
  model's tool-calling ("no multi-round tool loop") — the LLM only phrased
  findings that keyword tables and regex had already decided.
- `stage2/` + `fhir_adapter.py` (~1,400 lines) turned structured input into a
  normalized case object nobody's hospital produces.

The panel keeps only what was genuinely valuable and format-independent: the
clean case data, the clinical framing (two-axis grades, operability gate,
goals-of-care), and the planted-gap benchmark cases.

## The loop

```
load_context(case_id)          clean markdown chart + transcript, no FHIR
        │                       (reuses cases.get_case)
        ▼
Router (LLM)                   picks relevant specialists from the roster;
        │                       always-on floor added in code
        ▼
Round 1 — PARALLEL fan-out     every chosen specialist consults at once,
        │                       native knowledge, returns findings + claims + needs
        ▼
Reconciliation (LLM)           finds CONTRADICTIONS and DEPENDENCIES across claims
        │
        ▼
Round 2+ — CROSS-EXAMINE       broker-mediated: carry one specialist's claim to
        │  (bounded)            another, re-run only the involved specialists;
        │                       re-check for new conflicts each round
        ▼
Synthesis (LLM)                merge/dedupe/rank findings, build action ledger
        │                       (may keep/merge/drop — never invent)
        ▼
HARD GATES (code)              operability gate has the final word
        ▼
PanelResult
```

## Files

| File | Role |
|---|---|
| `context.py` | Clean case → one text brief. The entire ingestion story. |
| `roster.py` | Specialists as **roles** (not check-types), incl. always-on floor. |
| `router.py` | LLM picks who sits on the board this case. |
| `specialists.py` | One role-prompted LLM consult; also serves cross-exam. |
| `reconcile.py` | LLM finds tensions between specialists. |
| `orchestrator.py` | The loop above. Parallel fan-out + brokered rounds. |
| `synth.py` | Merge → ranked findings + action ledger. |
| `gates.py` | Operability gate, enforced in code. |
| `llm.py` | One Claude JSON helper (model, caching, tolerant parse). |
| `schema.py` | Self-contained data contracts (no FHIR/legacy imports). |
| `api.py` / `run.py` | FastAPI endpoint / CLI runner. |

## Design principles (so upgrades don't require a rewrite)

1. **Specialists are roles, not checks.** Adding one = one entry in `roster.py`.
   This is what lets the panel see the *whole patient* — Internal Medicine,
   Pharmacy, and Cardiology sit on the board alongside Oncology, so non-cancer
   problems get a seat by construction.
2. **Any specialist callable at any time.** The router chooses per case; there
   are no hard-wired predicate gates.
3. **Native knowledge now, EBM later — one seam.** Specialists reason from the
   model's own knowledge today. The upgrade slot is a future `evidence_provider`
   inside a specialist (e.g. Oncology pulling live trials/guidelines); the
   orchestrator never changes when a specialist's evidence source is swapped.
4. **Broker-mediated debate.** Specialists never message each other directly; the
   orchestrator carries claims between them. Every exchange is logged
   (`deliberation`) — the auditable rationale trail. Free peer-to-peer chat is a
   later upgrade the broker design can grow into.
5. **Knowledge is the model's job; safety is code's job.** Only the operability
   gate (and goals-of-care, next) are hard-coded — because they're safety rules,
   not clinical knowledge, and must not be prompt-mediated.

## Run it

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install anthropic fastapi "uvicorn[standard]" pydantic python-dotenv
cp .env.example .env   # add ANTHROPIC_API_KEY
export PANEL_MODEL=claude-sonnet-5   # optional; default is claude-sonnet-5

python -m app.panel.run hero_breast_escalation           # CLI, human-readable
python -m app.panel.run hero_breast_escalation --json     # raw JSON
uvicorn app.panel.api:app --reload                        # POST /board {"case_id": "..."}
```

## Not yet done (next steps)

- **Goals-of-care gate in code** (like operability). The `palliative_goc`
  specialist raises it now; promoting it to a hard precondition is the next gate.
- **Wire the existing frontend** to `POST /board` (Finding fields are kept
  compatible; `source_agent` → `source_specialist` is the one rename to map).
- **Delete the legacy path** (`stage2/`, `ingest/fhir_adapter.py`, canned
  `tools/`, old `orchestrator.py`) once the panel is validated end-to-end.
- **Benchmark harness**: run the panel across all `data/cases/*` and score against
  each `case_meta.json`'s `planted_gaps` (caught / missed / false-positive).
