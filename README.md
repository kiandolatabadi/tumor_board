# Tumor Board — Multi-Specialist Gap-Detection Assistant

An agentic assistant for oncology tumor boards. It reads a patient's chart and the
board's discussion, convenes a panel of specialist agents, and surfaces the gaps
the room *didn't* address — a missed fertility referral, an unconfirmed operability
check, a drug interaction, a stale goals-of-care conversation — each linked back to
its evidence in the chart or transcript.

It never makes the clinical call. It surfaces what's missing, grades how strong the
evidence is, and says how confident it is that the evidence fits *this* patient.

## How it works

The analysis is **agentic and format-free**: specialists reason over the clean
Markdown a clinician authors, using the model's own clinical knowledge. There is no
FHIR layer and no hard-coded decision logic — the clinical thinking is the model's
job; code only routes, bounds, and enforces safety rules.

```
clean markdown case (chart + board transcript)
        │
   Router (LLM) ── picks the specialists this case needs
        │           always-on: oncology · pharmacy · internal medicine
        ▼           on-demand: cardiology · genetics · fertility · surgery · … 
   Round 1 — PARALLEL fan-out: every chosen specialist reviews at once,
             returning findings + claims (positions) + open needs
        ▼
   Reconciliation (LLM) ── finds contradictions & dependencies between specialists
        ▼
   Cross-examination (broker-mediated, parallel) ── carries one specialist's claim
             to another for a second opinion; bounded rounds
        ▼
   Synthesis (LLM) ── merges/dedupes/ranks findings + builds an action ledger
        ▼
   HARD GATES in code ── e.g. a proposed procedure can't be shown "ready" unless
             operability was actually cleared (never prompt-mediated)
```

Every run is **bounded** — a per-run model-call budget, a request timeout, and caps
on rounds and conflicts — so it can't hang or run away.

Design detail: [`docs/panel-architecture.md`](docs/panel-architecture.md).

## Repository layout

```
backend/
  app/
    panel/          the agentic core (router, specialists, reconcile, synth, gates)
    cases.py        loads the clean case folders (the only "ingestion")
    config.py       model + client config
  tests/            panel regression test (runs the loop against a mock client)
frontend/           React + Vite UI (patient chart browser + panel findings)
data/cases/         patient cases: markdown chart by specialty + board transcript
docs/               architecture notes
DEPLOYMENT.md       how to host it (static frontend + server backend)
```

## Quickstart (local)

Needs **Python 3.11+**, **Node 18+**, and an **Anthropic API key**.

**Backend** (terminal 1):
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

Open http://localhost:5173, pick a patient, and click **Convene board**. A run makes
several model calls and takes ~1–2 minutes.

Prefer the terminal? `python -m app.panel.run hero_breast_escalation` prints a run.

## Data & cases

Cases live in `data/cases/<case_id>/` as plain Markdown grouped by specialty
(`oncology/`, `pathology/`, `radiology/`, …) plus a board transcript. Each case's
`case_meta.json` also carries a benchmark answer key (`planted_gaps`) — that key is
stripped at the API boundary and never served to a clinical view.

## Deployment

The frontend is static (any static host, e.g. GitHub Pages); the backend is a Python
server that holds the API key and must run on a server host (Render, Railway, Fly).
The key stays a server-side environment variable — never in the repo or the browser.
Full guide: [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Status & roadmap

Working: the full panel loop, the operability gate, the React UI, a mock-client
regression test. Next up:

- Goals-of-care as a second code-enforced gate (currently raised by a specialist).
- A code-level check that every finding's cited evidence exists in the chart.
- A benchmark harness scoring the panel against each case's planted gaps.
- Per-specialist evidence-provider seam for real EBM/guideline retrieval.

## License

MIT — see [`LICENSE`](LICENSE).
