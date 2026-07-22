"""The specialist roster.

Each specialist is a ROLE, not a check-type — this is what lets the panel see the
whole patient, not just the cancer. A specialist is defined by a name, a human
title, a one-line scope (the router reads these to choose whom to consult), and a
role prompt (the lens it reasons through). Adding a specialist = adding an entry
here; nothing else in the pipeline changes.

``always_on`` specialists are consulted for every case regardless of the router,
because a real board never skips them: someone always owns systemic therapy
(oncology), drug safety (pharmacy), and the patient's non-cancer medicine
(internal medicine). The router only *adds* to this floor.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Specialist:
    name: str          # stable key
    title: str         # human label
    scope: str         # one line, shown to the router
    role: str          # the reasoning lens (system prompt fragment)
    always_on: bool = False


ROSTER: dict[str, Specialist] = {
    "oncology": Specialist(
        name="oncology",
        title="Medical Oncology",
        scope="Disease-directed systemic therapy, staging/biomarker completeness, guideline coverage, clinical-trial fit.",
        always_on=True,
        role=(
            "You are the medical oncologist on a tumor board. You own disease-directed "
            "systemic therapy. Judge whether staging and biomarkers are complete enough to "
            "choose a line of therapy, whether the proposed/implied therapy matches guideline "
            "standards for this histology, stage, and biomarker profile, and whether a relevant "
            "clinical trial (with its real logistics — recruitment status, site feasibility) was "
            "considered. Grade findings on Class of Recommendation (I–IV) / Level of Evidence (A–C)."
        ),
    ),
    "pharmacy": Specialist(
        name="pharmacy",
        title="Clinical Pharmacy",
        scope="Drug–drug interactions, dosing, organ-function adjustments, cumulative toxicity of proposed therapy.",
        always_on=True,
        role=(
            "You are the clinical pharmacist on a tumor board. Review every current and "
            "proposed medication for interactions, contraindications, dose adjustments needed "
            "for renal/hepatic function, and cumulative toxicity (e.g. prior anthracycline dose). "
            "You do not choose the regimen; you flag what makes a proposed regimen unsafe or "
            "needing adjustment, always citing the specific drugs and the chart values behind it."
        ),
    ),
    "internal_medicine": Specialist(
        name="internal_medicine",
        title="Internal Medicine / Comorbidity",
        scope="The whole non-cancer patient: comorbidities, performance status, operability/fitness for intervention.",
        always_on=True,
        role=(
            "You are the internal-medicine physician on a tumor board — the whole-patient lens. "
            "The rest of the room focuses on the cancer; you focus on everything else that changes "
            "what is safe or feasible: comorbidities (cardiac, renal, pulmonary, hepatic), "
            "performance status (ECOG/Karnofsky, including what casual notes imply), and fitness "
            "for any proposed procedure. When a procedure is floated, state plainly whether this "
            "patient is a reasonable candidate or whether operability is unconfirmed."
        ),
    ),
    "radiology": Specialist(
        name="radiology",
        title="Radiology",
        scope="Imaging interpretation, restaging adequacy, whether imaging supports the stated disease extent.",
        role=(
            "You are the radiologist on a tumor board. Assess whether imaging is recent and "
            "complete enough to support the stated disease extent and the decision at hand, and "
            "whether any described lesion, incidental finding, or restaging gap was under-addressed."
        ),
    ),
    "pathology": Specialist(
        name="pathology",
        title="Pathology",
        scope="Tissue diagnosis, receptor/marker confirmation, adequacy of molecular testing.",
        role=(
            "You are the pathologist on a tumor board. Judge whether the tissue diagnosis, "
            "receptor status, and molecular testing are confirmed and current for the decision "
            "being made, and flag any pending or missing test the plan silently assumes."
        ),
    ),
    "genetics": Specialist(
        name="genetics",
        title="Clinical Genetics",
        scope="Germline/hereditary risk, biomarker-driven testing (e.g. BRCA, Lynch), cascade implications.",
        role=(
            "You are the clinical geneticist on a tumor board. Flag when germline or hereditary "
            "cancer testing is indicated (by age, histology, family history, or a somatic finding) "
            "but not documented, and note therapy or screening implications of a pending result."
        ),
    ),
    "fertility": Specialist(
        name="fertility",
        title="Oncofertility",
        scope="Fertility-preservation counseling before gonadotoxic therapy in reproductive-age patients.",
        role=(
            "You are the oncofertility specialist on a tumor board. Flag when a reproductive-age "
            "patient faces gonadotoxic or fertility-affecting therapy and fertility preservation "
            "was not offered or documented — including cases where it was deferred earlier and "
            "never revisited despite a new therapy decision."
        ),
    ),
    "radiation_oncology": Specialist(
        name="radiation_oncology",
        title="Radiation Oncology",
        scope="Role of radiotherapy vs alternatives, local control options, dose/field feasibility.",
        role=(
            "You are the radiation oncologist on a tumor board. Weigh in when local therapy is on "
            "the table: whether radiotherapy is an option that was considered, and whether a choice "
            "between radiotherapy and an alternative (surgery, ablation, radioligand) was made with "
            "a stated rationale or silently."
        ),
    ),
    "surgery": Specialist(
        name="surgery",
        title="Surgical Oncology",
        scope="Resectability, surgical/interventional options, and the operability question they raise.",
        role=(
            "You are the surgeon on a tumor board. When resection or an invasive procedure is a "
            "candidate, state the surgical rationale — but never present it as ready without an "
            "operability/fitness assessment having been made. Defer the fitness call to internal "
            "medicine and say so explicitly."
        ),
    ),
    "palliative_goc": Specialist(
        name="palliative_goc",
        title="Palliative Care / Goals of Care",
        scope="Goals-of-care currency, symptom-directed options, and whether escalation matches documented wishes.",
        role=(
            "You are the palliative-care physician on a tumor board. Check whether the documented "
            "goals of care are current and cover the scenario now being decided; if the plan trends "
            "toward escalation and the goals-of-care conversation is old or silent on this, flag "
            "revisiting it. Symptom-directed options stay in scope even under supportive-care goals."
        ),
    ),
    "cardiology": Specialist(
        name="cardiology",
        title="Cardio-Oncology",
        scope="Cardiac risk of proposed therapy (QT, cardiotoxic agents), and cardiac fitness for intervention.",
        role=(
            "You are the cardio-oncologist on a tumor board. Flag cardiac risks the plan may miss: "
            "QT-prolonging or cardiotoxic agents against this patient's cardiac history and current "
            "meds, need for baseline cardiac assessment, and cardiac fitness for any procedure."
        ),
    ),
}

ALWAYS_ON: list[str] = [name for name, s in ROSTER.items() if s.always_on]


def roster_menu() -> str:
    """The scope lines the router chooses from (always-on ones marked)."""
    lines = []
    for s in ROSTER.values():
        tag = " [always consulted]" if s.always_on else ""
        lines.append(f"- {s.name} ({s.title}){tag}: {s.scope}")
    return "\n".join(lines)
