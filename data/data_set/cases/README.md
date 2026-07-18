# Case benchmark index

Consolidated view of the planted gaps across all cases (synthesised from each
`case_meta.json`) — the §1a mini-benchmark spec. Nothing clinical is added here;
this is a map from cases to the checks that should catch them.

## Which agent owns which check

| Check (in `catching_check`) | Owner |
|---|---|
| `check_guideline_coverage` | **guidelines agent** (`agents/guidelines`) — mine |
| `search_trials` | **trials agent** (`agents/trials`) — mine |
| `check_operability` | orchestrator / teammate |
| `check_drug_interactions` + `flag_stale_data` | orchestrator / teammate |
| decision-rationale extraction, `live_question` | orchestrator / teammate |

## Planted gaps by case

| Case | Cancer | Board date | Planted gap(s) | Catching check | Expected count |
|---|---|---|---|---|---|
| `hero_breast_escalation` | breast | 2026-06-25 | fertility deferred (G-BR-01); BR-2201 closed/distant; liver metastasectomy operability; goals-of-care stale (G-BR-05) | guideline_coverage ×2 · search_trials · operability | **4** |
| `variant_1_no_rationale` | breast | 2026-07-09 | switch to capecitabine with no stated rationale | decision-rationale | 1 |
| `variant_2_stale_interaction` | breast | 2026-07-16 | warfarin + capecitabine, renal panel >4 mo stale (INT-002) | flag_stale_data → drug_interactions | 1 |
| `variant_3_brca_pending` | breast | 2026-07-23 | BR-1187 PARP trial needs *resulted* germline BRCA; test is pending | search_trials (two-axis confidence) | 1 |
| `variant_4_lung_control` | NSCLC | 2026-07-11 | none — negative control | — | **0** |
| `variant_5_cardiac_comorbidity` | breast | 2026-07-30 | anthracycline re-challenge with 2019 myocarditis / LVEF 48% (G-BR-04) | guideline_coverage + live_question | 1 |

## Two things the checks must get right on this dataset

1. **Forks resolve the hero gaps in the chart.** In variants 1/2/3/5 the follow-up
   oncology note explicitly closes fertility ("referral was placed and completed
   2026-07-02"), goals-of-care ("revisited 2026-07-02"), operability
   (`not_cleared`, dropped), and BR-2201 (confirmed closed). The guidelines/trials
   agents must read those as **addressed**, not re-fire them. → shelf-card
   `addressed_when` keywords should include the fork phrasings (e.g.
   `"fertility preservation referral"`, `"goals-of-care was revisited"`).

2. **`expected_findings_count` counts GAPS, not all findings.** The guidelines
   agent also returns `status: "addressed"` items (e.g. NSCLC first-line coverage
   in the control case is *satisfied*). For the benchmark, filter to
   `status == "gap"` (guidelines) / `verdict != "could_enter"` (trials) before
   counting, or the negative control will look like a false positive.

## Noise documents (hero) — must NOT fire a finding

`radiology/2023-08-14_incidental_thyroid_nodule.md`,
`gynecology/2023-08-22_annual_wellwoman_exam.md`,
`medications/medication_reconciliation_2024-03-06.md`.
