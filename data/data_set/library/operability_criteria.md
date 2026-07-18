# Operability / Feasibility Check Criteria (Internal, Fictional stub for `check_operability`)

Before any surgical or invasive-procedure option (metastasectomy, ablation, resection) may be presented as a cleared recommendation, the following must be confirmed and documented:

1. **Performance status** — ECOG 0-1 (2 considered case-by-case)
2. **Number and distribution of lesions** — oligometastatic (generally 3 or fewer), technically resectable margins achievable
3. **Hepatic reserve** (for liver-directed procedures) — adequate remnant liver volume, Child-Pugh A equivalent function
4. **Cardiac clearance** — if general anesthesia required, baseline cardiac risk assessment on file
5. **Systemic disease control** — no rapidly progressive extrahepatic/extrapulmonary disease that would make local control moot

**Output states:** `cleared` (all criteria confirmed) / `not_yet_assessed` (no check has been run) / `not_cleared` (a criterion fails). Any surgical option surfaced to the findings feed without an explicit `cleared` result must be labeled "guideline-preferred — operability not yet confirmed," never presented as a clean recommendation.
