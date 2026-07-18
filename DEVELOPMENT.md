# Development

Scaffold for the Tumor Board Gap-Detection Assistant. See `README.md` for the
product spec and `CLAUDE.md` (local, gitignored) for architecture notes.

```
backend/            Python — Claude tool_use orchestrator + FastAPI
  app/
    main.py         FastAPI app: /health, /case, /analyze
    orchestrator.py single Messages call with tool_use; enforces the operability gate in code
    case_schema.py  normalized oncology case (TumorBoardCase) + completeness()
    ingest/         source-agnostic adapters: raw record -> TumorBoardCase
      fhir_adapter.py  FHIR envelope -> normalized case (robust value readers)
      transcript.py    transcript STRING -> structured lines for the UI
    agents/         agentic layer — nuance the deterministic path can't see
      schema.py        Enrichment output contract (the template)
      enrich.py        enrichment agent + deterministic grounding verifier
    goc.py          goals-of-care precondition — gates whether guidance runs at all
    stage2/         Stage 2 (adopted split): raw record -> PatientCaseBundle
      bundle.py        contract-shaped models (element_ids, presence, staleness)
      adapter.py       to_bundle(); enums.py, ids.py (deterministic derivations)
    schema.py       Finding / ActionItem contracts (signals kept separate)
    config.py       model id + Anthropic client (from .env)
    tools/          one module per sub-check, over canned data
    data/           synthetic case (real contract shape) + canned lookup tables
  tests/            operability gate + GOC precondition + ingestion (no API key needed)
frontend/           Vite + React + TS — findings panel + action ledger + gaps
  src/
    App.tsx, api.ts, types.ts, components/
```

## Target architecture: two-stage split (ADOPTED 2026-07-18)

The go-forward design is a two-person split with a typed seam. Governing docs:
`docs/architecture-delta.md` (narrative) and `docs/stage-interface-contract.yaml`
(authoritative, `status: ACCEPTED`).

- **Stage 2 — patient data structuring + transcript (James):** raw record → `PatientCaseBundle`
  (normalized facts with stable `element_id`s + mechanical `presence`/`staleness`). No clinical
  judgment; "gap" must not appear in its output.
- **Stage 3 — guidance + gap assessment (partner):** `PatientCaseBundle` + `GuidancePack` +
  `TranscriptBundle` → `FindingSet` + `ActionLedger`. Guideline coverage is a deterministic join,
  grades are copied from guidance rules, provenance is a structured `evidence[]` ledger.

Build in parallel against a committed golden fixture (`fixtures/contract/v1/`); neither owner edits a
fixture unilaterally (a fixture change is a contract change). The current `backend/` below is the
pre-split monolith being migrated toward this shape — notably `completeness()` is slated for retirement
in favor of `presence` + guidance rules.

## Data model (current, pre-split — two layers)

Incoming data lands as the flexible **FHIR envelope** (Abridge's real contract:
`patient_context`, `encounter_fhir.related_resources` grouped by FHIR type,
`transcript` string). `app/ingest` normalizes it into a typed **`TumorBoardCase`**
— the oncology essence (diagnosis, staging, biomarkers, performance status,
comorbidities, meds, goals-of-care). The adapter is deliberately robust:

- reads both full FHIR shapes (`CodeableConcept`, `valueQuantity`) and simplified
  strings, so real and hand-authored data both parse;
- everything optional — partial data still fits; absent essentials become **gaps**
  via `TumorBoardCase.completeness()`, which feed the gap detector;
- lossless — unrecognized resources are preserved in `case.unmapped`, not dropped.

To add a new data source, write an adapter that returns a `TumorBoardCase` and
register it in `app/ingest/__init__.py`; nothing downstream changes. Verified
against all 25 real records in `data/abridge/synthetic-ambient-fhir-25` (0 errors).

## Backend

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml`
+ `uv.lock`). Install uv, then:

```bash
cd backend
uv sync --group dev       # create .venv + install locked deps (incl. pytest)
cp .env.example .env      # add your ANTHROPIC_API_KEY

uv run uvicorn app.main:app --reload   # http://localhost:8000
uv run pytest -q                       # tests run without an API key
```

Add a dependency with `uv add <pkg>` (or `uv add --group dev <pkg>`); it updates
`pyproject.toml` and `uv.lock` together.

Endpoints: `GET /case` (bundled synthetic case), `POST /analyze` (empty body →
runs the orchestrator on the bundled case), `GET /health`.

## Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api → :8000
```

Click **Run analysis** to call `POST /api/analyze` and render findings + ledger.

## Agentic layer (`app/agents/`)

The deterministic path only sees *coded* fields. The **enrichment agent** reads the
unstructured prose (transcript, `longitudinal_summary`, `note`) and emits *candidate*
inferences the structured path misses — performance status implied by casual speech,
an uncoded comorbidity, an implicit goals-of-care concern. It runs before the
orchestrator, so its leads can raise a check the coded data never triggered.

Guardrails (all enforced in code, testable without an API key):
- **`raises_check` runs deterministically.** An inference with `raises_check` (a
  `ToolName` enum — not a free string, so typos fail loudly via a drift test) makes
  `run_triggered_checks()` actually run that tool, folding the inferred fact into its
  inputs. For operability the result *gates* the findings: a surgical finding can only
  stand as `cleared` if a real cleared result exists, and a blocking result overrides
  a model-declared `cleared` → `not_confirmed`. The tool result is required before a
  surgical option is emitted; it is not prompt-mediated.
- **Source-cited or dropped, and quotation ≠ entailment.** Every inference carries a
  verbatim `source.quote`. `verify_grounding()` confirms it appears in the source and
  *repairs* the line/speaker; unverifiable citations go to `rejected`. It also flags
  **dropped negations** (quoting "a candidate for resection" out of "*not* a candidate
  for resection") as a meaning inversion and rejects them.
- **Separate channel.** Enrichment is its own section of `AnalysisResult` — never
  merged into the grounded case/findings. The UI renders it with distinct styling.
- **Graceful degradation.** No API key / any agent error → empty `Enrichment` with a
  `skipped_reason`; the deterministic pipeline still produces findings.

`POST /enrich` runs the agent alone (isolated testing). `POST /analyze` runs
enrichment → orchestrator. Both need `ANTHROPIC_API_KEY`; without it `/enrich`
returns a skipped result and `/analyze` errors in the orchestrator call.

Adding an agent: give it a schema (its output template) in `agents/`, a forced
structured-output tool, a run function with graceful degradation, and a
deterministic verifier. Mirror the enrichment agent.

## Preconditions (`app/goc.py`) — checked before options are produced

A **precondition layer** sits in front of option-producing work. There are two, and they share one
rule: *a permissive outcome requires a positive, checkable result — never merely the absence of a
contrary one.*

| | Operability gate | GOC precondition |
|---|---|---|
| Permissive outcome | present surgery as `cleared` | skip guidance entirely |
| Requires | a real `cleared` tool result | a valid supportive-care record |
| On absence | force `not_confirmed` | do **not** skip |
| Runs | after the model, at emit | **before** the guidance call |

`evaluate_goc()` answers *does this patient want disease-directed care at all?* Two clinical rules
(clinician-reviewed):

- **Recency is event-relative.** A goals-of-care record written *before* a major treatment event is
  stale regardless of its date. `goc_date > most_recent_major_event_date AND age_days <= threshold`.
  Event invalidation is checked first — it is the more actionable answer.
- **Suppression requires affirmative evidence.** Only `VALID_SUPPORTIVE_ONLY` sets
  `authorizes_skip = True`. `ABSENT`, `STALE_BY_AGE`, `INVALIDATED_BY_EVENT` and
  `CONTRADICTED_BY_ROOM` never do. Missing goals of care is the least-informed state, not a licence
  to withhold options.

- **Scope mismatch blocks suppression.** `GoalsOfCare.covers` (closed `CareDomain` vocabulary) plus
  `scope_source` record what a conversation addressed. A record touching no disease-directed domain
  yields `SCOPE_MISMATCH` — a resuscitation-only DNR cannot withhold trial matching. Unknown scope
  (`scope_source == absent`) is NOT a mismatch and falls through. Stage 3 joins via
  `goc.covers_domain()`, which returns `None` for unknown — unknown is not False.
- **An undated event is unprovable recency, not absence.** `major_events()` keeps undated events; an
  undated event of an invalidating kind yields `TIMELINE_INCOMPLETE` (no skip) plus a `data_gap_note`
  naming them. Dropping them would fail silently in the dangerous direction.

**Inference asymmetry:** a grounded `goals_of_care` inference may *invalidate* a documented record
(the room is revising it live) but may never *authorize* a skip. Model output triggers conservative
behaviour only — the same rule that keeps `grounded` out of the enrichment tool schema.

**The skip narrows scope, it does not empty it.** A supportive-care record suppresses
*disease-directed* guidance only; symptom-directed options (palliative radiotherapy for pain, symptom
control) stay in scope. `permitted_scope: CareScope` carries the signal and the skip path emits a
symptom-directed review action item. Deterministic filtering by care intent needs an `intent` field
on guidance rules — Stage 3, when the pack lands. Branch on `permitted_scope`, not `authorizes_skip`.

**A skip is never silent.** `goc_skip_result()` emits a finding stating the decision and its basis
plus action items to confirm the record and review symptom-directed options. It carries no
`recommendation_grade` — no guidance rule matched, so there is nothing to copy one from.

**FHIR date spellings matter.** `fhir_adapter._fhir_date()` reads `performedDateTime` /
`performedPeriod` / `occurrenceDateTime` (and `onsetDateTime` / `onsetPeriod` / `recordedDate` for
conditions), collapsing `Period` to its `start`. The 25 real Abridge records use `performedPeriod`
exclusively — reading only `performedDateTime` left every real procedure undated. After the fix: 515
events across the 25 records, 0 undated. Add new spellings here rather than at each call site.

Adding a precondition: give it an evaluation function returning a typed result with one explicit
permissive flag, run it before the work it gates, and make its decision visible in the output.

**Owned by Stage 3, left in `goc.py` deliberately** — do not edit these from Stage 2:
`MAX_GOC_AGE_DAYS` (threshold varies by clinical scenario), `INVALIDATING_EVENT_KINDS` (which events
invalidate a record is a clinical call), and care-intent filtering. They move to the guidance pack
with the Stage 3 owner.

## Notes

- All clinical data is **synthetic/factice** — canned lookup tables in
  `backend/app/data/`, not live clinical APIs. Say so in the demo.
- The finding schema keeps `recommendation_grade` (evidence strength) and
  `match_confidence` (fit to this patient) as separate axes — do not merge them.
- Surgical/invasive findings are gated through `check_operability` in
  `orchestrator.gate_operability`, enforced in code, not prompt-only.
