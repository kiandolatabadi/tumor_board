# Library crosswalk (library entry → check → JSON target)

Maps each fictional library entry to the check that consumes it and the JSON
schema it should be translated into. This is integration guidance for the agent
machinery — the clinical content stays physician-owned.

## Guidelines → `check_guideline_coverage` (shelf JSON, `agents/guidelines/shelf/`)

Grades already use the Class/Level convention → drop verbatim into
`recommendation_grade` (e.g. `"I / B"`), citation into `evidence_ref`. Authoring
schema: `agents/guidelines/shelf/AUTHORING.md`.

| Library entry | Target specialist (shelf file) | Notes |
|---|---|---|
| G-BR-01 fertility preservation | `fertility_preservation` | `applies_when`: breast, reproductive age, gonadotoxic therapy. `addressed_when`: `"fertility preservation referral"`, `"reproductive endocrinology"` |
| G-BR-02 endocrine vs. cytotoxic re-challenge | `guideline_coverage` | the *rationale* gap is teammate's decision-rationale check; the coverage card is mine |
| G-BR-03 re-biopsy / receptor reconfirmation | `guideline_coverage` (or `biomarker_completeness`) | receptor status at recurrence |
| G-BR-04 cardiac risk with anthracycline re-exposure | `guideline_coverage` | **needs a way to represent prior anthracycline + cardiac history** — see alignment gap below |
| G-BR-05 goals-of-care review at status change | `goals_of_care` | `staleness`/status-change logic; `addressed_when`: `"goals-of-care was revisited"` |
| G-BR-06 germline before PARP | `germline_testing` | confirms resulted (not pending) germline status |
| G-LU-01 NSCLC first-line by biomarker | `guideline_coverage` | control case — should resolve to `addressed`, not a gap |
| G-LU-02 NSCLC goals-of-care at dx | `goals_of_care` | control case — current in the chart |

> **You are translating the breast treatment guidelines PDF → JSON.** The
> `Target specialist` column tells you which `shelf/*.json` file each becomes;
> the `specialist` field in each card must equal that name.

## Trials → `search_trials` (trial JSON, `agents/trials/trials/`)

Authoring schema: `agents/trials/AUTHORING.md`. I can translate these four for
you (they're mine to own).

| Library trial | Verdict it should drive | Depends on |
|---|---|---|
| BR-2201 ribociclib | ⚠️ eligible-but-**unavailable** (closed enrollment, ~310 mi) | recruitment status + site distance |
| BR-1187 PARP | 🟡 possible — needs *resulted* germline BRCA (pending → not eligible yet) | germline BRCA resulted, not pending |
| BR-0942 capecitabine re-challenge | eligibility + current renal panel | overlaps flag_stale_data |
| LU-3305 pembrolizumab | ✅ clean match (control) | PD-L1 ≥ 50, no driver |

## Other (orchestrator / teammate)

| Library entry | Check |
|---|---|
| `drug_interactions.md` (INT-001..004) | `check_drug_interactions` |
| `operability_criteria.md` | `check_operability` |

---

## Two alignment gaps between the dataset and my current agents

1. **Trials agent has no logistics gate.** BR-2201 needs to be flagged as
   *closed + distant* (hero `gap_trial_logistics`), but the trials agent
   currently treats `recruitment_status`/site as info fields, not verdict
   drivers. Needs a logistics layer (open/closed + site distance).

2. **Confidence on pending data.** For BR-1187 with germline *pending*
   (variant_3), the trials agent returns `possible_with_more_info` but currently
   sets `match_confidence` high/moderate — the case wants it **low** (evidence
   strong, patient-fit confidence low). Needs the confidence heuristic tuned so
   a pending/absent deciding fact → low.

3. **G-BR-04 needs cardiac + anthracycline representation.** The guidelines
   matcher extracts cancer/stage/age/sex/biomarkers/therapy-class but not prior
   anthracycline exposure or cardiac history, so G-BR-04 can't fire from
   structured fields alone yet — either extend extraction or make it a
   free-text/agent-judged path.
