"""The board loop.

    router → parallel fan-out → reconcile → cross-examine (broker) → synthesize → gate

Round 1 runs every chosen specialist in parallel. Reconciliation finds the
tensions. Cross-examination brokers a targeted second opinion for the top conflicts
— and now runs those in PARALLEL too, so a debate round costs one call's latency,
not one per party. Everything is bounded: a call budget, a per-request timeout
(see config), a cap on conflicts examined, and a small round cap. A board run
can no longer run away.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from .context import load_context
from .gates import apply_operability_gate
from .llm import CallBudgetExceeded, reset_call_budget
from .reconcile import find_conflicts
from .roster import ROSTER
from .router import select_specialists
from .schema import Conflict, DeliberationEntry, PanelResult, SpecialistOpinion
from .specialists import consult
from .synth import synthesize

MAX_ROUNDS = int(os.getenv("PANEL_MAX_ROUNDS", "1"))       # cross-examination passes after the parallel round
MAX_PARALLEL = int(os.getenv("PANEL_MAX_PARALLEL", "6"))    # specialists consulted concurrently
MAX_CONFLICTS = int(os.getenv("PANEL_MAX_CONFLICTS", "3"))  # top conflicts cross-examined per round


def _cross_examine(
    conflicts: list[Conflict],
    opinions: dict[str, SpecialistOpinion],
    ctx,
    round_no: int,
    pool: ThreadPoolExecutor,
) -> list[DeliberationEntry]:
    """Broker every party of every conflict IN PARALLEL: hand each involved
    specialist the other side's position and re-consult. Updates ``opinions`` in
    place; returns the log entries."""
    tasks: list[tuple[Conflict, str, str]] = []
    for conflict in conflicts:
        parties = [n for n in conflict.specialists if n in ROSTER and n in opinions]
        for target in parties:
            opposing = "; ".join(
                f"{opinions[n].title} says: {opinions[n].summary}" for n in parties if n != target
            )
            challenge = (
                f"The board found a {conflict.kind} on '{conflict.topic}': {conflict.description}. "
                f"{opposing or 'Another specialist has raised a concern.'}"
            )
            tasks.append((conflict, target, challenge))
    if not tasks:
        return []

    def _run(task: tuple[Conflict, str, str]):
        conflict, target, challenge = task
        return task, consult(ROSTER[target], ctx, cross_exam=challenge)

    entries: list[DeliberationEntry] = []
    for (conflict, target, challenge), updated in list(pool.map(_run, tasks)):
        opinions[target] = updated
        entries.append(DeliberationEntry(
            round=round_no, topic=conflict.topic, prompt_to=target,
            opposing_claim=challenge, response=updated.summary,
        ))
    return entries


def run_board(case_id: str) -> PanelResult:
    """Run the full panel over a case folder and return the board output."""
    reset_call_budget()  # the call budget is per-run
    ctx = load_context(case_id)
    truncated = False

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        # Router: who sits on this board?
        names, _reason = select_specialists(ctx)

        # Round 1 — parallel fan-out.
        opinions_list = list(pool.map(lambda n: consult(ROSTER[n], ctx), names))
        opinions: dict[str, SpecialistOpinion] = {o.specialist: o for o in opinions_list}

        # Reconcile → bounded, parallel cross-examination rounds.
        conflicts: list[Conflict] = find_conflicts(list(opinions.values()))
        deliberation: list[DeliberationEntry] = []
        examined: set[str] = set()
        rounds = 1
        try:
            while conflicts and rounds <= MAX_ROUNDS:
                batch = [c for c in conflicts if c.topic not in examined][:MAX_CONFLICTS]
                if not batch:
                    break
                rounds += 1
                deliberation += _cross_examine(batch, opinions, ctx, rounds, pool)
                for c in batch:
                    c.resolved = True
                    c.resolution = f"cross-examined in round {rounds}"
                    examined.add(c.topic)
                # Only re-scan for new conflicts if another round is actually allowed.
                if rounds <= MAX_ROUNDS:
                    conflicts += [c for c in find_conflicts(list(opinions.values())) if c.topic not in examined]
        except CallBudgetExceeded:
            truncated = True  # stop deliberating; synthesize what we have

    # Synthesis + hard gate (outside the pool).
    ordered = [opinions[n] for n in names if n in opinions]
    try:
        findings, ledger, synth_trunc = synthesize(ctx, ordered, conflicts, deliberation)
    except CallBudgetExceeded:
        findings, ledger, synth_trunc = [f for o in ordered for f in o.findings], [], True
    findings = apply_operability_gate(findings, ordered)

    return PanelResult(
        case_id=ctx.case_id,
        specialists_consulted=names,
        findings=findings,
        action_ledger=ledger,
        conflicts=conflicts,
        deliberation=deliberation,
        rounds=rounds,
        opinions=ordered,
        truncated=truncated or synth_trunc,
    )
