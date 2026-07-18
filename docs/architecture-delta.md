# Architecture Delta — amendments to `README.md` §5

> **Editor's note (relocated to `docs/`, committable copy).** Moved out of the repo
> root so it reaches both owners via git. The authoritative interface contract was
> copied alongside it to **`docs/stage-interface-contract.yaml`**; the advisor's full
> working artifacts stay local in `.boilerplate/` (gitignored) by design. One factual
> correction was applied to §4.1 residual gap 1 — model-initiated operability results
> *are* captured (`orchestrator.py:251`); the original claim was verified stale against
> current code. Marked inline.

**Decision (2026-07-18): ADOPTED.** The two-person Stage 2 / Stage 3 split described here is the
agreed go-forward architecture. `docs/stage-interface-contract.yaml` is `status: ACCEPTED` and is the
authoritative seam. Ownership: **Stage 2 (patient data structuring + transcript) — James; Stage 3
(guidance + gap assessment) — partner.** The current `backend/` is the pre-split monolith and is
being migrated toward this shape; sections below mark what exists vs. what is still to build.

**Status:** partially implemented. `README.md` remains the historical spec; this file is the delta
against it. The enrichment pass (§5) is **built and tested** — full suite 63/63 passing. The
Stage 2 / Stage 3 seam (§3) is **adopted; the Stage 2 side is scaffolded** (schema + adapter + golden
fixture, 18 contract tests) while Stage 3's guidance-as-input is not started. Each section marks its
own state.

**Audience:** the two component owners. Read this before writing code against the other person's half.

**Provenance:** derived from an architecture assessment run on the repo (README + CLAUDE.md + the
current `backend/` tree). The advisor's full working artifacts remain in `.boilerplate/` (gitignored,
kept local by choice). The authoritative interface contract has been committed to
**`docs/stage-interface-contract.yaml`** and is the authoritative version of the summary in §3 below.

---

## 1. What changed, in one line

The README's single Claude call with six model-callable tools becomes a **three-stage pipeline with
a typed seam**, built by two people in parallel, where the checks that were previously "tools the
model *may* call" become **deterministic joins that always run**.

## 2. Topology

```
patient files ──► [2] normalize ──► TumorBoardCase ──┐
                                                     ├──► [E] enrich ──► inferred[]
transcript file ────────────────────────────────────►┘                  + raises_check
                                                                              │
                                                              deterministic triggered checks
                                                              (run_triggered_checks — in code)
                                                                              │
                                                          GOC PRECONDITION ◄──┘
                                                          (evaluate_goc — §8)
                                                             │           │
                                              authorizes_skip│           │otherwise
                                                             ▼           ▼
                                              disclosed skip      [3] orchestrator ◄── guidance /
                                              (never silent)      + operability gate     canned tables
                                                     │                   │
                                                     └─────────┬─────────┘
                                                               ▼
                                                    FindingSet + ActionLedger
```

| Stage | What it is | Owner | State |
|---|---|---|---|
| **1** | Live STT feed | — | **DESCOPED.** Static transcript file. Deferred, not cancelled. |
| **2** | Patient data structuring — files/folder → `PatientCaseBundle` | James | **scaffolded** — `app/stage2/` schema + adapter, 18 contract tests, golden fixture at `fixtures/contract/v1/` |
| **E** | Enrichment pre-pass — source-cited inferences that feed [3] | parallel session | **implemented** |
| **P** | Goals-of-care precondition — gates whether guidance runs at all (§8) | — | **implemented, 23 tests** |
| **3** | Guidance + gap assessment — deterministic join, then bounded model call | Partner | orchestrator exists; guidance-as-input not started |

**Ordering note.** Enrichment is a **pre-pass** — not a parallel channel, and not a consolidator. It
runs *before* the orchestrator and hands it source-cited leads plus deterministically-executed check
results. Enrichment supplies; the orchestrator synthesizes; the gate constrains. Putting a model in
the consolidating position would invert the governing principle and place it downstream of the
operability gate, where it could reintroduce an ungated surgical option.

### Stage-by-stage delta

| README says | Amended | Why |
|---|---|---|
| One Messages call does everything | Deterministic adapter → guidance join → bounded model call | Lets two people build in parallel; makes the hard rules enforceable in code |
| `check_guideline_coverage` is a tool the model may call | Guidance is a **structured input**; coverage is a deterministic join that always runs | A check the model *may* call is a check that *may not* run |
| `flag_stale_data` is a tool | Stage 2 emits `age_days`; the **threshold** is a guidance rule | Separates mechanical fact from clinical opinion |
| Trial matching inside the model | `applies_when` filter runs first (a `WHERE` clause), model judges the remainder | Deterministic control, bounded semantic judgment |
| "surfaced live as the meeting happens" | **Not live.** Static transcript, findings emitted once | Stage 1 is descoped. Do not claim per-utterance liveness |
| `recommendation_grade: "IIa/B"` | Split: `class_of_recommendation` + `level_of_evidence` | Compound strings can't be filtered or validated |
| `source_agent` | **Deleted.** Replaced by `evidence[]` | Residue of the rejected multi-agent panel; `evidence[]` subsumes it |
| Operability enforced "in code" | Gate-owned object, **absent from the emit tool schema** | See §4 — the current implementation is bypassable |

Unchanged from the README: the action-item ledger stays a structurally separate end-of-meeting
output; `match_confidence` stays orthogonal to evidence grade; canned/"factice" data stays canned
and labelled; Tier 2 `check_practice_pattern` stays Tier 2.

## 3. The seam

Stage 2 emits `PatientCaseBundle`. Stage 3 consumes it. **Field names and types are in
`stage-interface-contract.yaml` — that file is authoritative, this section is orientation.**

The rule that keeps the seam clean, applicable by either owner without conferring:

> **If populating a field requires a clinical opinion, it belongs to Stage 3.
> The word "gap" must not appear in Stage 2's output.**

Consequence: **`case_schema.completeness()` is deleted.** It hardcodes which absences count as gaps —
a clinical judgment — inside the data schema. Its five remaining checks are re-authored as `GEN-*`
rules in the guidance pack (the sixth — goals of care — has already been removed: the precondition
in `goc.py` is now its sole owner). Stage 2 emits `presence` (mechanical); Stage 3 joins it against
guidance.

Without this, the collision is guaranteed: Stage 3 writes "stage III NSCLC requires EGFR" and finds
Stage 2 already emitting a hardcoded `biomarkers missing`, with no arbiter between them.

### How to work in parallel without blocking

A **golden fixture** — `fixtures/contract/v1/patient_case_bundle.json` — hand-authored and committed
**before either build starts**.

- Stage 2 asserts `adapter(source_record) == golden`.
- Stage 3 loads the golden file as its input and **never calls Stage 2 during development**.

Both suites go green in isolation; integration is a no-op if both pass. Stage 2 needs no API key
(zero model calls). Stage 3 needs no working adapter.

**One governance rule: a fixture change is a contract change. No unilateral edits.**

## 4. Invariants that must survive the split

**The operability gate — FIXED, verified.** The original defect (`gate_operability` only relabelling
`not_applicable`, so a model-emitted `"cleared"` passed untouched) is closed. `gate_operability` is
now **default-deny**: a finding proposing a procedure may stand as `cleared` only if a real
`check_operability` result cleared it, and a blocking result (`cleared: false`) overrides a
model-declared `cleared`. Absence of evidence forces `not_confirmed` plus the README's required
relabel, *"guideline-preferred — operability not yet confirmed."*

What makes it bite is `_operability_input` folding the inferred fact into the tool's inputs before
dispatch, so an **uncoded** comorbidity actually changes the deterministic result rather than merely
being narrated to the model. Proven end-to-end: inferred-only COPD → `raises_check` →
`check_operability` → not cleared → a model-declared `cleared` lobectomy forced to `not_confirmed`.

Two residual gaps, both narrow, both failing safe:

1. **~~Clearance is reachable only via the enrichment path.~~ CORRECTED — resolved in current code.**
   The original assessment claimed `op_results` was seeded before the tool loop and never updated
   inside it. Verified stale: `orchestrator.py:251` appends model-initiated `check_operability`
   results to `op_results` inside the loop, so they accumulate across tool-use iterations and are
   present when the terminal-iteration gate runs. `cleared` is reachable via the model path.
   (With enrichment skipped and the model calling no operability tool, `op_results` is empty and
   surgical findings still fail safe to `not_confirmed`.)
2. **Clearance isn't bound to the procedure cleared.** `blocking` / `cleared_exists` are computed
   globally, so clearing a mediastinoscopy would license a lobectomy in the same run. `blocking`
   takes precedence, so it fails safe — but the binding is missing.

When guidance becomes a structured input, add the primary structured trigger
(`guidance_rule.intervention_class ∈ {surgical, invasive_procedure}`) unioned with the existing
`_proposes_procedure` keyword classifier, which stays as the backstop for model-originated findings.

**The evidence ledger.** `evidence: [{kind, ref}]`, kinds:
`case_element | guidance_rule | transcript_line | tool_result | absence`.

Because `element_id`, `line_id`, and `rule_id` are stable across the seam, a validator holding only
the input bundles and the output `FindingSet` can verify every citation **without observing the
run**. That property is what lets the invariant survive two people building separately — it is worth
protecting deliberately.

**Grades are copied, never generated.** `class_of_recommendation` and `level_of_evidence` are copied
from the matched guidance rule. A finding with no `guidance_rule` in its `evidence[]` may not carry
them.

## 5. The enrichment pass — IMPLEMENTED

**Built and tested** (`test_enrich.py` + `test_triggered_checks.py`, 10 tests; full suite 63/63).
`backend/app/agents/`. This section describes what exists, not a proposal.

**Intent:** capture nuance the deterministic path structurally cannot — performance status implied
by casual speech, a comorbidity mentioned but never coded, a goals-of-care concern raised in
conversation, a concern raised then dropped.

**Shape:** a model call with a forced structured-output tool (`report_inferences`), followed by a
**deterministic verifier**. The model authors candidates; nothing is trusted until code confirms it.

### The three properties that make it trustworthy

**1. The model cannot assert its own grounding.** `SourceRef.grounded` is set only by
`verify_grounding`, and it **does not appear in `ENRICHMENT_TOOL`'s input schema** — the model has
no way to express it, so it cannot claim it. This is the same pattern the operability gate uses, and
it is strictly stronger than overwriting a model-supplied value: there is no value to overwrite and
no precedence ambiguity. Apply this pattern to any field where the model's claim would otherwise be
self-certifying.

**2. Quotation is verified, and meaning-inversion is caught.** Every observation must carry a
verbatim `source.quote`; if it isn't found in the transcript or free text, the observation is
rejected. Substring matching alone would accept *"a candidate for resection"* quoted out of *"she's
**not** a candidate for resection"* — so `_negation_inversion` rejects a quote with a negation token
adjacent to but absent from the matched span, while correctly exempting quotes that carry the
negation themselves. Rejected items are retained in `Enrichment.rejected` rather than discarded.

**3. `raises_check` executes deterministically.** An observation may set
`raises_check: ToolName` — a closed enum, kept in sync with the tool registry by a drift test, so a
renamed tool fails loudly instead of silently never firing. `run_triggered_checks` then **runs that
tool in code, before the model**, and `_operability_input` folds the inferred fact into the tool's
inputs. That last part is the crux: an *uncoded* comorbidity changes the deterministic result rather
than merely being narrated to the model.

### Contract with the rest of the pipeline

- **Enrichment output is never merged into the grounded case.** `Enrichment` is a distinct section;
  `InferredObservation.inferred: Literal[True]` marks the channel. The UI renders it separately
  (`InferredPanel.tsx`).
- **No `class_of_recommendation` / `level_of_evidence`.** There is no guidance rule to copy from, and
  emitting a grade here would fabricate clinical authority — the failure the two-axis design exists
  to prevent. Correctly absent; keep it that way.
- **Inferences are leads, not findings.** The orchestrator receives them labelled
  `UNCONFIRMED`, while triggered-check results are labelled `AUTHORITATIVE`.
- **Degrades gracefully.** Any failure, including a missing API key, yields an empty `Enrichment`
  with `skipped_reason`; the pipeline still runs. Note the interaction with default-deny in §4.1.

### Still open

- Enrichment currently reads the normalized case *and* the transcript, so it can flag contradictions
  between what was said and what the chart holds. Worth an explicit test — that capability isn't
  covered yet.
- When guidance becomes a structured input, decide whether an inference that matches a guidance rule
  should be promoted into the rule-backed channel, or stay inferred with a cross-reference.

## 6. Defects

**Fixed and verified** (parallel session): `raises_check` unwired; grounding accepting inverted
meaning; `raises_check` as a free string. All three confirmed in code, suite green.

**Still live, silent, confirmed on disk** — all on the Stage 2 side:

1. **`case_schema.py:117`** documents `PriorTreatment.kind` as `'surgery' | 'systemic' | 'radiation'`,
   but **`fhir_adapter.py:248`** hardcodes `kind="procedure"`. A Stage 3 rule matching
   `kind == "surgery"` matches nothing, forever, with no error. Close the enum, fix the adapter.
   *Fixed on the Stage 2 side:* `stage2/adapter.py` classifies into the closed `TreatmentKind` enum
   (`_treatment_kind`). The defect is now confined to the pre-split ingest adapter.
2. **`fhir_adapter.py:131`** — `_prov()` falls back to a positional ref. Reorder the source and every
   citation silently re-points. Mint stable `element_id`s. *Fixed on the Stage 2 side:*
   `stage2/ids.py` mints stable `element_id`s; the pre-split adapter still has the fallback.
3. **`completeness()` is still called** from `orchestrator.py:195` and `main.py:60`. Per §3 it is to
   be deleted and its five remaining checks re-authored as `GEN-*` guidance rules (its goals-of-care
   check is already gone — GOC staleness/absence now lives only in the precondition, and
   `flag_stale_data` explicitly disclaims it too). Until then, "what counts as a gap" has two owners.

Also: `max_tokens=4096` with a bare `json.loads` in `orchestrator.py` means truncated output yields
zero findings rather than partial ones. (Enrichment already degrades gracefully; the orchestrator
does not.)

## 7. Open questions

| # | Question | Blocks |
|---|---|---|
| 1 | **Who owns the guidance pack?** Under this design it holds the system's entire clinical substance — 6–12 rules, grades, `applies_when`, `intervention_class`. Currently unassigned and unreviewed. | Stage 3 — their whole build is a join against it |
| 2 | ~~Should model-initiated `check_operability` results count toward clearance?~~ **RESOLVED in code:** they do — `orchestrator.py:251` appends them inside the tool loop, so they gate alongside enrichment-triggered ones (§4.1 correction). | — |
| 3 | Should clearance bind to a specific procedure rather than the run? (§4.2) | Stage 3 |
| 4 | ~~`.boilerplate/` is gitignored — how does the interface contract reach both owners?~~ **RESOLVED:** contract committed to `docs/stage-interface-contract.yaml`. | — |

Q1 is the one to resolve first. Stage 3 cannot start without at least a skeleton pack, and its
clinical content is the part no amount of architecture makes correct.

## 8. The precondition layer — IMPLEMENTED (goals of care)

**Built and tested.** `backend/app/goc.py`, `backend/tests/test_goc.py` (23 tests, suite 63/63).
Clinical rules reviewed by the clinician partner.

### It is a layer, not a one-off

There are now two preconditions, and they are the same shape:

> **Don't present X as actionable until precondition Y has been checked — and a permissive outcome
> requires a positive, checkable result, never merely the absence of a contrary one.**

| | Operability gate | GOC precondition |
|---|---|---|
| Question | is this physically feasible? | does the patient want this? |
| Permissive outcome | present surgery as `cleared` | skip guidance entirely |
| Requires | a real `cleared` tool result | a valid supportive-care record |
| On absence | force `not_confirmed` | do **not** skip |
| Runs | after the model, at emit | **before** the guidance call |

Expect a third (drug interaction before a systemic option) and a fourth. When one arrives, add it to
this layer rather than hand-wiring it — ad-hoc gate #3 is how the original prompt-mediated defect
happened. **Any new finding source, and any new option-producing path, enters through these
preconditions.**

### The two clinical rules

**1. Recency is event-relative, not calendar-only.** A goals-of-care conversation recorded *before* a
major treatment event is stale regardless of its date — the event is precisely what would change the
answer. Both conditions must hold:

```
goc_valid = goc_date > most_recent_major_event_date  AND  age_days <= threshold
```

Event invalidation is evaluated *before* calendar age because it is the more specific and more
actionable answer: "recorded before the lobectomy" tells a clinician something "180 days old" does
not.

**2. Suppression requires affirmative evidence.** Guidance may be skipped only on a positive, recent,
event-valid record documenting supportive care. `ABSENT`, `STALE_BY_AGE`, `INVALIDATED_BY_EVENT`, and
`CONTRADICTED_BY_ROOM` all yield `authorizes_skip = False`. Missing goals of care is the *least*
informed state, not a licence to withhold options — and silent withholding is invisible harm, since
nobody can audit what was never shown.

`GocStatus` has eight values; exactly one sets `authorizes_skip = True`.

**3. An undated event is unprovable recency, not absence.** `major_events()` retains events that carry
no usable date, and an undated event of an invalidating kind yields `TIMELINE_INCOMPLETE` — no skip,
plus a `data_gap_note` naming the events so a provider can see *why* the record could not be
confirmed. Dropping them would be a silent failure in the dangerous direction: an undated surgery
that in fact postdates the record would vanish, and the record would look valid.

This was not hypothetical. `fhir_adapter.py` read only `performedDateTime`, which **does not occur
anywhere in the 25 real Abridge records** — they use `performedPeriod` (515 occurrences). Every real
procedure arrived undated. `_fhir_date()` now reads across FHIR spellings (`performedDateTime`,
`performedPeriod`, `occurrenceDateTime`; `onsetDateTime`, `onsetPeriod`, `recordedDate` for
conditions) and collapses `Period` to its `start`. Measured after the fix: **515 events across the 25
records, 0 undated.** The `TIMELINE_INCOMPLETE` path remains for sources that genuinely lack dates —
capture what dates exist, surface the rest to the provider.

### The inference asymmetry

A grounded `InferenceKind.goals_of_care` observation from the room:

- **may invalidate** a documented record → `CONTRADICTED_BY_ROOM`. If goals of care are being
  discussed *now*, the chart is under live revision and cannot be relied on to skip.
- **may never authorize** a skip. A model-inferred "she wants supportive care" does not suppress
  guidance on its own.

This is the general rule this system runs on, applied again: **model output triggers conservative
behaviour, never permissive behaviour.** Same reason `grounded` is absent from the enrichment tool
schema and `cleared` requires a real tool result. Only a *verified* quote counts as a room signal.

### The skip narrows scope; it does not empty it

A supportive-care record suppresses **disease-directed** guidance only. Symptom-directed options —
palliative radiotherapy for pain, symptom control — remain clinically appropriate and are not
withheld. `GocEvaluation.permitted_scope` carries this as a `CareScope`
(`all_options` | `symptom_directed_only`), and `goc_skip_result()` emits a second action item
directing symptom-directed review.

**Stage 3 completes this.** Deterministic filtering by care intent needs guidance rules to carry an
`intent` field; until the pack exists, the precondition emits the scope signal and the skip path
states plainly that symptom-directed options were not covered by the run. Branch on
`permitted_scope`, not on `authorizes_skip`, when the pack lands.

### A skip is never silent

When guidance is skipped, `goc_skip_result()` emits a finding stating the decision and its basis —
the record's date, its age, and the absence of an intervening event — plus action items to confirm
the record and to review symptom-directed options. Skip the guidance; never skip the disclosure.

The finding carries **no `recommendation_grade`**: no guidance rule matched, so there is nothing to
copy a grade from. Same rule as enrichment (§5).

A clinically credible system is one that declines to recommend and says exactly why — not one that
always produces options.

### Two Stage 2 requirements this creates

Both belong in the golden fixture **before** either owner starts:

1. **A dated event timeline, not a flattened snapshot.** Event-relative recency is impossible if the
   bundle only carries current state. `major_events()` derives events mechanically from
   `diagnosis_date` and `prior_treatments` (including a recorded progression in `response`), keeping
   undated ones. `PatientCaseBundle` must preserve dates *and* types — and must read every FHIR date
   spelling the source uses, per the `performedPeriod` finding above. Where a date genuinely does not
   exist, carry the event with a null date rather than dropping it, so the gap is reportable.
2. ~~**GOC scope, not just a date.**~~ **DONE — contract 1.1.0.** `GoalsOfCare` now carries
   `covers: list[CareDomain]` (8-value closed vocabulary) and `scope_source`
   (`coded` | `derived_from_text` | `absent`), in both `case_schema` and the Stage 2 bundle. The
   vocabulary lives in `app/care_domains.py` — dependency-free, so neither layer depends on the
   other and there is exactly one definition.

### Handoff to Stage 3 — code changes to be made on the Stage 3 side

Three pieces of clinical opinion currently sit in `goc.py`, on the wrong side of the seam. They are
marked as such in the source and are **deliberately left in place**: the corresponding code edits
belong to the Stage 3 owner, together with the guidance pack, and should not be made from Stage 2.

| Item | Today | Belongs in |
|---|---|---|
| `MAX_GOC_AGE_DAYS = 180` | module constant in `goc.py` | a guidance rule (threshold varies by scenario — six months for stable disease, days for a fast-moving one) |
| `INVALIDATING_EVENT_KINDS` | module set in `goc.py` | the guidance pack — which event kinds invalidate a prior record is a clinical call, and the clinician partner should enumerate it |
| Care-intent filtering | `permitted_scope` signal only | guidance rules need an `intent` field so symptom-directed options can be filtered deterministically |

Stage 2 keeps what is mechanical: emitting dated events and their kinds.

### Still open

- **Scope mismatch is enforced.** A record whose recorded scope touches no disease-directed domain
  (`systemic_therapy | surgery | radiation | clinical_trials`) yields `SCOPE_MISMATCH` and cannot
  suppress guidance — the README's "or doesn't cover this scenario" case. A resuscitation-only DNR
  conversation no longer withholds trial matching. **Unknown scope is not a mismatch**: a bare
  "supportive care only" is a global statement and still falls through.
- **`covers_domain(ev, domain)` is the Stage 3 primitive** — returns `True`/`False`, or **`None` when
  scope is unknown**. Unknown is not False; do not treat it as coverage either way.
- The **research agent** (§7 discussion) sits downstream of this precondition: its auto-trigger on
  empty guidance must not fire when `authorizes_skip` is true, and its fallback condition must key on
  *disease-specific* rules, since `GEN-*` completeness rules match nearly every case.
