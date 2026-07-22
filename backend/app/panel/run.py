"""CLI: run the panel over a case and print the board output.

    python -m app.panel.run hero_breast_escalation
    python -m app.panel.run hero_breast_escalation --json

Needs ANTHROPIC_API_KEY (copy backend/.env.example to backend/.env).
"""
from __future__ import annotations

import argparse
import sys

from .orchestrator import run_board
from .schema import PanelResult


def _print_human(r: PanelResult) -> None:
    print(f"\n╔══ TUMOR BOARD PANEL — {r.case_id} ══")
    print(f"║ specialists consulted: {', '.join(r.specialists_consulted)}")
    print(f"║ deliberation rounds: {r.rounds}   conflicts: {len(r.conflicts)}"
          + ("   [output truncated]" if r.truncated else ""))
    print("╚" + "═" * 60)

    if r.conflicts:
        print("\n── CONFLICTS ──────────────────────────────")
        for c in r.conflicts:
            mark = "✔ resolved" if c.resolved else "✗ open"
            print(f"  [{c.kind}] {c.topic} ({', '.join(c.specialists)}) — {mark}")

    print(f"\n── FINDINGS ({len(r.findings)}) ─────────────────────────")
    for i, f in enumerate(r.findings, 1):
        grade = f.recommendation_grade or "—"
        op = "" if f.operability_status == "not_applicable" else f"  [operability: {f.operability_status}]"
        print(f"\n{i}. [{grade} | match {f.match_confidence:.0%}] {f.issue}{op}")
        print(f"   → {f.recommendation}")
        print(f"   src: {f.source_specialist}  ·  evidence: {f.evidence_ref}")
        print(f"   live Q: {f.live_question}")

    if r.action_ledger:
        print(f"\n── ACTION LEDGER ({len(r.action_ledger)}) ─────────────────")
        for a in r.action_ledger:
            dl = f" (by {a.deadline})" if a.deadline else ""
            print(f"  • [{a.owner}]{dl} {a.action}")
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the tumor-board panel over a case.")
    p.add_argument("case_id", help="folder name under data/cases/")
    p.add_argument("--json", action="store_true", help="print raw JSON instead of a summary")
    args = p.parse_args(argv)

    try:
        result = run_board(args.case_id)
    except KeyError:
        print(f"unknown case: {args.case_id}", file=sys.stderr)
        return 2
    except RuntimeError as e:  # missing API key, etc.
        print(str(e).splitlines()[0], file=sys.stderr)
        return 1

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
