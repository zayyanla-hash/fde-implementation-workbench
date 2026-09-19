"""Scenario registry — how to add a new customer scenario without forking the engine.

A scenario = fixture directory + metadata + optional engine knobs.
New scenarios reuse every pipeline stage; only fixtures/rules change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    fixture_dir: str
    description: str


SCENARIOS: dict[str, Scenario] = {
    "vendor_payments_v1": Scenario(
        key="vendor_payments_v1",
        title="Acme Industrial — supplier invoice intake & payment approval",
        fixture_dir="fixtures",
        description=(
            "Messy AP inbox (emails, contract memo, policy note) + CSV invoice extract + "
            "mock vendor-master/PO APIs -> normalized config -> validated decisions with "
            "retry, escalation, approval gate, and audit trail."
        ),
    ),
}

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


def fixture_dir_for(scenario_key: str) -> Path:
    try:
        sc = SCENARIOS[scenario_key]
    except KeyError:
        valid = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown scenario {scenario_key!r} (valid: {valid})")
    return (PACKAGE_ROOT / sc.fixture_dir).resolve()


def list_scenarios() -> list[Scenario]:
    return list(SCENARIOS.values())
