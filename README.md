# Tumor Board Agent — Hackathon Master Plan
**Abridge × Anthropic × Lightspeed, July 18, 2026 — Shack15, Ferry Building SF**

---

## 0. The one decision that matters most: which project are you building?

You have two candidates:

- **A — Gap-Detection Assistant (your idea):** listens to the real human tumor board, reads the chart/labs/trials/interactions in parallel, and surfaces what the room *didn't* address — each flagged item linked back to the moment (or absence) in the transcript.


---


| Criterion | Weight (Rd 1) | A — Gap-Detection Assistant | B — Multi-agent panel |
|---|---|---|---|
| Impact | 20% | ✅ solves a pain point clinicians will actually accept | ⚠️ real adoption path is much harder — most oncologists will not accept a system that makes the call |
| Execution | 30% | ✅ narrower scope = more likely to be complete and polished by 5pm | ⚠️ multi-agent debate systems are notoriously hard to make *look* finished in one day; easy to demo as flaky or scripted |
| Technical Complexity | 20% | ✅ still technically real: transcript parsing, retrieval, tool orchestration, evidence-linking | ✅ scores well here almost by definition |
| Creativity/Originality | 25% | ⚠️ "AI listens to a meeting and flags gaps" is a legible, less novel shape | ✅ scores well here — but "simulated multi-agent panel" is also becoming a common hackathon trope, so novelty isn't guaranteed either |

Net: B isn't a clear win on the rubric — it trades Impact and Execution risk for Creativity and Technical Complexity that A can *also* capture if built well (§5).


### 1a. Differentiation — tiered, so it's unambiguous what to actually build

Several teams will build "transcript + chart + trial matcher." The list below is split into three tiers on purpose — Tier 1 is what the demo does not work without, Tier 2 is worth it only if Tier 1 is solid with time to spare, Tier 3 is what you *say* in the pitch/Q&A without building it. Don't let Tier 2/3 ideas eat time that Tier 1 needs — a judge will forgive a missing roadmap item; they won't forgive a broken core loop.

**Tier 1 — must build**

1. **Two-axis confidence, not one number.** Grade every finding on the real dual-axis clinical convention: Class of Recommendation (I–IV: should / reasonable / may consider / should not) crossed with Level of Evidence (A/B/C: strength of the studies behind it) — a recognized clinical grading system, name it explicitly in the pitch. Add a second, orthogonal axis: the agent's own confidence that it matched the right evidence to *this specific patient* (right biomarker, right staging, complete data). Keep the two axes visually and verbally separate — "the evidence is strong (I-A), but I'm only moderately confident this is the right biomarker for this patient" is the most honest possible framing of what an LLM can and can't know.
2. **Evidence layer → "to be addressed with the patient," with real numbers.** Not "consider trial NCT12345" but "this trial reported a 12% absolute improvement in 2-year progression-free survival vs. standard of care (n=450)." Directly extends the "patient communication" direction Abridge's own dataset README names — say that explicitly in the pitch.
3. **Trial matching with real logistics, not just biomarker fit.** "Meets 4 of 5 inclusion criteria, missing confirmed EGFR status" beats a binary yes/no — and eligibility alone isn't enough: filter by recruitment status (open/closed) and site feasibility too. A molecularly perfect trial 300 miles away with closed enrollment is not a useful match.
4. **Comorbidity/operability gating — enforced in the architecture, not just mentioned in a flag.** Before the orchestrator surfaces any option requiring physical intervention (surgery, an invasive procedure), it must call a feasibility/operability-check tool *first*. The option is either presented as cleared, or explicitly labeled "guideline-preferred — operability not yet confirmed." Never silently present a surgical option as ready without that check having run. This is a hard architectural rule, not a soft nice-to-have — see §5.
5. **Goals-of-care as first-class metadata, with a staleness/mismatch flag.** Don't just store it — actively check it: if the emerging plan trends toward aggressive intervention and the documented goals-of-care conversation is old, or doesn't cover this scenario, generate a distinct action item: "consider revisiting goals of care with the patient." The option to *revisit* goals of care, not just to record them once, is one of the most commonly missed steps in real tumor boards — treat surfacing that possibility as a required output, not a passive field.
6. **Decision-rationale extraction.** For every point where the room actually chooses between options (e.g. radiotherapy vs. a nuclear-medicine alternative), extract the stated rationale if one was given, and flag clearly when a choice was made *without* an explicit rationale spoken aloud: "team selected radiotherapy over I-131; no rationale stated in discussion." This is the "reason about why this line was chosen over that line" capability — it reuses the same live-question/reporting mechanism you're already building for gaps, just pointed at *decisions* instead of *omissions*.
7. **Live, directly addressable question.** One specific, answerable question surfaced the moment a gap is caught — "Given confirmed HER2+ status, has trial NCT12345 been considered?" — shown live in the UI *and* logged in a running written record for anyone who misses it. Live and reported, not one or the other.
8. **End-of-meeting action-item ledger.** `{action, owner, deadline, linked_finding}`, pulled from who in the room actually said they'd do what. This is pure synthesis over data you already have — no new tool, no new data source — and it's the deliberately *human-triggered* version of closing the loop (see the automation question below).
9. **Your own mini-benchmark, demoed live.** 4–5 planted-gap variants of your core case, run against your own pipeline, reported as "caught 8/9, 1 false positive." Cheap because it's just re-running what you already built.

**Tier 2 — build only if Tier 1 is solid with time to spare**

- **Performance-status inference from casual speech** (ECOG/Karnofsky implied by context — "she's still doing the school run" — rather than formally stated). Genuinely valuable, genuinely harder NLP problem; not core-critical.
- **Local practice-pattern memory across sessions** — e.g. "this board has favored radiotherapy over this type of nuclear medicine option in 7 of the last 9 similar cases." For a demo, fake this with a small canned "historical decisions" lookup table (same pattern as the drug-interaction table) and one more tool call — cheap to build. Frame it strictly as a QA/audit signal ("worth confirming this reflects patient-specific factors rather than default habit"), never as pressure to conform — and mention once in the pitch that a real deployment of this would need real governance around who sees it and how it's used, since practice-pattern tracking across a care team touches on individual clinician profiling if handled carelessly.
- **EHR-ready board summary note** — a formatting pass generating a chart-ready summary of the discussion/decision, directly analogous to Abridge's own after-visit-summary concept applied to the board instead of the visit. Cheap, nice bonus, not essential.
- **Unresolved-disagreement tracking** — flagging when the room raises then drops a concern. Fine secondary signal; genuine unresolved disagreement is a rare event in real tumor boards, so it stays a small bonus check, never the pitch's centerpiece.


## 3. Environment & tooling checklist (do tonight, verify tomorrow morning)

**Data prep**
- [ ] **On the real Abridge dataset (`synthetic-ambient-fhir-25`):** it's 25 synthetic, Synthea-based, single-clinician ambient encounters (wellness exams, prenatal intakes, hospital/SNF/hospice admissions), one JSON record each with `id`, `metadata`, `patient_context` (FHIR Patient + longitudinal summary), `encounter_fhir` (FHIR Encounter + related resources grouped by type), `transcript`, `note`, and `after_visit_summary`. It is **not** tumor-board data — there's no multidisciplinary case-conference format, and the two cancer-adjacent records are hospice admissions where the patient has already declined further treatment (nothing left to decide, nothing to catch). Don't force this dataset's *content* into the demo. Do reuse its *schema* (`schema.json`'s field names, and the "related resources grouped by FHIR type" convention) to author your own synthetic tumor-board case in the same JSON contract Abridge itself uses — real engagement with the host's data model, your own oncology content.
- [ ] One fictional but internally consistent patient case built in that schema shape: staging, biomarkers, key labs, current meds, imaging note — structured as `Condition` / `Observation` / `MedicationRequest`-style resources the way the real dataset groups things by FHIR type.
- [ ] One fake multi-specialist transcript (5 speakers — e.g. `ONCOLOGIST:`, `RADIOLOGIST:`, `SURGEON:`, `PATHOLOGIST:`, `NURSE_COORDINATOR:`, extending the real dataset's `DR:`/`NURSE:`/`FAMILY:` speaker-label convention) with 2–3 *deliberate gaps* — this is what your demo will "catch," and later seeds the mini-benchmark cases in §1a.
- [ ] A small canned lookup table for drug interactions and trial matches (you will not hit real clinical APIs reliably in a demo; fabricate plausible entries and say so clearly — "factice data" is explicitly fine per your own framing and keeps you honest with judges).
- [ ] 4–5 additional planted-gap variants of the core case, built once the core loop works, for the live mini-benchmark in §1a.

---

## 5. Architecture 

```
transcript (streamed or chunked)  ─┐
patient chart / labs / meds       ─┼─►  Orchestrator (Claude, tool use)
canned trial list                 ─┤        │
canned interaction table          ─┘        ├─► sub-check: guideline coverage
                                             ├─► sub-check: trial eligibility
                                             ├─► sub-check: drug interactions
                                             └─► sub-check: stale/missing data
                                                        │
                                             synthesized findings feed
                                             {issue, evidence_ref, recommendation,
                                              recommendation_grade (e.g. "IIa/B"),
                                              match_confidence, patient_facing_note,
                                              live_question, source_agent}
                                                        │
                                                   /ui findings panel
                                          (timestamped, linked to transcript line)
```

Build the orchestrator as **one Claude Messages API call with tool_use (function calling)**, where each "sub-check" is a tool the model can call (`check_drug_interactions`, `search_trials`, `check_guideline_coverage`, `flag_stale_data`, `check_operability`, `check_practice_pattern` if you get to Tier 2). This is the standard, well-documented pattern (Anthropic's own tool-use docs) and is far more predictable to demo live than a simulated multi-turn debate between separate agent processes. If you want the heavier version, the **Claude Agent SDK** (recently renamed from the Claude Code SDK) natively supports subagents, MCP tool connections, and session persistence in Python/TypeScript — genuinely relevant here, but it's more infrastructure than you need for a one-day demo, and learning it live adds risk. Reasonable call: default to plain tool-use for the product; only reach for the Agent SDK if your teammate already knows it well.

**Hard architectural rule (Tier 1, non-negotiable):** any tool output that proposes a surgical or invasive-procedure option must route through `check_operability` *before* it's allowed into the findings feed. The orchestrator should not be able to surface "surgery" as a clean recommendation without that call having happened first — enforce this in code (e.g. the synthesis step rejects/relabels any surgical option missing an operability result), not just via prompting, since a judge poking at edge cases is exactly how a prompt-only version of this rule quietly breaks.

Each finding carries several separate signals, deliberately not collapsed into one score: `recommendation_grade` is the real Class-of-Recommendation / Level-of-Evidence pair (how strong is the evidence itself); `match_confidence` is the agent's own certainty that it applied that evidence correctly to *this* patient (right biomarker, right staging, complete data); `rationale_status` records whether the room gave an explicit reason for a choice or not (`stated` / `not stated`); `patient_facing_note` holds the plain-language, numbers-included translation for the "to be addressed with the patient" layer; `live_question` holds the one clear, directly answerable question the board can act on in the moment, surfaced live as the meeting happens, not just logged for later. This is the "correctly uncertain, evidence-shown" framing that's genuinely your strength; lean into it. It also directly answers a judge's hardest question: "how do you know it's not hallucinating a drug interaction?" → "it doesn't get to say anything without a source; here's the lookup it called."

**A second, separate output, generated once at the end of the meeting rather than live per-utterance:** the action-item ledger — `{action, owner, deadline, linked_finding}` — synthesized from who in the room actually said they'd do what. Keep this structurally distinct from the live findings feed in your code and in the UI; it's a different kind of artifact (a to-do list for humans) rather than another finding, and it's the honest, human-triggered answer to "does this system close the loop" (§1a, Tier 3) rather than the system executing anything itself.

Timeline

| Time | Block | Detail |
|---|---|---|
| 10:30–12:30 | Hacking begins | Data + orchestrator skeleton. Get one tool call working end-to-end (mirrors §6) before touching UI. |
| 12:30–1:00 | — | Buffer / lunch starts at 1:00 |
| 1:00–2:00 | Lunch served | Eat away from the screen for 15 min if you can; you're judged live at 5, protect your energy. |
| 2:00–3:30 | Hacking | All sub-check tools wired in; findings feed rendering in the UI, linked to transcript moments. |
| 3:30–4:30 | Hacking | Freeze new features. Polish the demo path only. Record the 1-minute demo video now, not at 4:55. |
| 4:30–5:00 | Buffer | Submit the form (public repo, demo video/link, all teammates added) with margin — don't submit at 4:59. |
| 5:00 | Submissions due | — |
| 5:00–6:45 | Round 1 judging | ~3 min demo + 1-2 min Q&A. Rehearse the demo out loud at least twice before this. |
| 6:00 | Dinner | — |
| 7:00–8:00 | Round 2 (top 6) | Equal weighting across all four criteria this round — your Impact/ethics narrative matters as much as the build here. |
| 8:15 | Winners announced | — |

