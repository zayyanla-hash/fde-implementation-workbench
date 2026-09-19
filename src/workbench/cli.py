"""CLI: demo / run / approve / audit / serve / list-scenarios.

Examples:
  python -m workbench demo
  python -m workbench run --scenario vendor_payments_v1
  python -m workbench approve INV-1004 --approve --approver maria --reason "one-off solvent buy"
  python -m workbench serve --port 8765
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench.approval import ApprovalGate  # noqa: E402
from workbench.config import Settings  # noqa: E402
from workbench.render import render_pending, render_run  # noqa: E402
from workbench.scenarios import fixture_dir_for, list_scenarios  # noqa: E402
from workbench.workflow import run_fixture_scenario  # noqa: E402

_LAST_RUN: dict[str, object] = {}  # in-process cache so `approve` can follow `run`


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workbench", description="FDE implementation workbench")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="run the end-to-end synthetic demo (deterministic)")
    d.add_argument("--rules", default=None)
    d.add_argument("--no-flaky", action="store_true", help="disable flaky-vendor failure injection")
    d.add_argument("--json", action="store_true")

    r = sub.add_parser("run", help="run a scenario pipeline")
    r.add_argument("--scenario", default=os.getenv("WORKBENCH_SCENARIO", "vendor_payments_v1"))
    r.add_argument("--rules", default=None)
    r.add_argument("--audit-dir", default=None)
    r.add_argument("--json", action="store_true")

    a = sub.add_parser("approve", help="resolve one escalated invoice from the last in-process run")
    a.add_argument("invoice_id")
    a.add_argument("--approve", action="store_true")
    a.add_argument("--reject", action="store_true")
    a.add_argument("--approver", default="")
    a.add_argument("--reason", default="")

    sub.add_parser("pending", help="show approval queue from the last in-process run")
    sub.add_parser("list-scenarios", help="list registered scenarios")

    s = sub.add_parser("serve", help="start the local HTTP API (stdlib only)")
    s.add_argument("--port", type=int, default=int(os.getenv("WORKBENCH_PORT", "8765")))

    return p


def _flaky_plan(disable: bool) -> dict[str, int]:
    if disable:
        return {}
    n = int(os.getenv("WORKBENCH_FLAKY_VENDOR_FAILS", "1"))
    return {"V-HOOLI": n} if n > 0 else {}


def cmd_demo(args: argparse.Namespace, settings: Settings) -> int:
    fixture = fixture_dir_for(settings.scenario)
    rules = Path(args.rules) if args.rules else None
    result, engine = run_fixture_scenario(
        fixture,
        rules_path=rules,
        audit_path=settings.audit_path_for("demo"),
        flaky_vendor_fails=_flaky_plan(args.no_flaky),
        max_tool_attempts=settings.max_tool_attempts,
    )
    _LAST_RUN["result"] = result
    _LAST_RUN["engine"] = engine
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("=" * 72)
        print("FDE WORKBENCH — END-TO-END DEMO (synthetic, offline, deterministic)")
        print("=" * 72)
        print(render_run(result))
        print()
        print("Next: python -m workbench pending | python -m workbench serve --port 8765")
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    fixture = fixture_dir_for(args.scenario)
    rules = Path(args.rules or settings.rules_path) if (args.rules or settings.rules_path) else None
    audit_dir = Path(args.audit_dir or settings.audit_dir)
    import uuid as _uuid
    run_id = f"run-{_uuid.uuid4().hex[:8]}"
    result, engine = run_fixture_scenario(
        fixture,
        rules_path=rules,
        audit_path=audit_dir / f"{run_id}.jsonl",
        flaky_vendor_fails={"V-HOOLI": settings.flaky_vendor_fails} if settings.flaky_vendor_fails else {},
        max_tool_attempts=settings.max_tool_attempts,
    )
    _LAST_RUN["result"] = result
    _LAST_RUN["engine"] = engine
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_run(result))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    if "result" not in _LAST_RUN:
        print("no in-process run yet — run `python -m workbench demo` first (same process).", file=sys.stderr)
        return 2
    if bool(args.approve) == bool(args.reject):
        print("pass exactly one of --approve / --reject", file=sys.stderr)
        return 2
    from workbench.models import RunResult as RR
    from workbench.workflow import WorkflowEngine as WE
    result: RR = _LAST_RUN["result"]  # type: ignore[assignment]
    engine: WE = _LAST_RUN["engine"]  # type: ignore[assignment]
    gate = ApprovalGate(result.decisions)
    try:
        d = gate.resolve(args.invoice_id, approve=args.approve, approver=args.approver, reason=args.reason)
    except (KeyError, ValueError) as exc:
        print(f"approval failed: {exc}", file=sys.stderr)
        return 1
    engine.record_resolution(d)
    print(f"{d.invoice.invoice_id} -> {d.decision} ({d.decision_reason})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.cmd == "demo":
        return cmd_demo(args, settings)
    if args.cmd == "run":
        return cmd_run(args, settings)
    if args.cmd == "approve":
        return cmd_approve(args)
    if args.cmd == "pending":
        if "result" not in _LAST_RUN:
            print("no in-process run yet — run `python -m workbench demo` first.")
            return 2
        from workbench.models import RunResult as RR
        print(render_pending(_LAST_RUN["result"]))  # type: ignore[arg-type]
        return 0
    if args.cmd == "list-scenarios":
        for sc in list_scenarios():
            print(f"{sc.key}: {sc.title}\n  {sc.description}")
        return 0
    if args.cmd == "serve":
        from workbench.server import serve
        serve(port=args.port)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
