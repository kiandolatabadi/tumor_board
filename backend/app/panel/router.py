"""Router: an LLM decides which specialists this case needs.

This replaces the legacy deterministic predicate triage. Any specialist in the
roster is selectable at any time; the model reads the case brief and the roster
menu and returns the relevant set. The always-on floor is added in code so the
model can never drop oncology, pharmacy, or internal medicine.
"""
from __future__ import annotations

from .context import BoardContext
from .llm import call_json
from .roster import ALWAYS_ON, ROSTER, roster_menu

_SYSTEM = (
    "You are the coordinator of a tumor board. Given a patient case, decide which "
    "specialists should be consulted. Choose every specialist whose expertise is "
    "relevant to a decision in this case — err toward inclusion; a specialist who "
    "finds nothing is cheap, a missing specialist is a missed gap. Do NOT list the "
    "always-consulted specialists; they are added automatically.\n\n"
    "Return ONLY JSON: {\"specialists\": [\"name\", ...], \"reason\": \"one line\"}, "
    "using names exactly as given in the menu."
)


def select_specialists(ctx: BoardContext) -> tuple[list[str], str]:
    """Return (ordered specialist names to consult, one-line reason).

    Always-on specialists lead the list; the router's picks follow, de-duplicated
    and filtered to known roster names. Falls back to the full roster if the call
    yields nothing parseable — better to over-consult than to silently under-run."""
    user = (
        f"SPECIALIST MENU:\n{roster_menu()}\n\n"
        f"CASE BRIEF:\n{ctx.brief()}\n\n"
        "Which non-always-on specialists are relevant?"
    )
    try:
        data, _ = call_json(_SYSTEM, user)
        picked = [n for n in data.get("specialists", []) if n in ROSTER]
        reason = str(data.get("reason", "")).strip()
    except Exception:
        picked, reason = list(ROSTER), "router unavailable — consulting full roster"

    ordered: list[str] = list(ALWAYS_ON)
    for name in picked:
        if name not in ordered:
            ordered.append(name)
    return ordered, reason
