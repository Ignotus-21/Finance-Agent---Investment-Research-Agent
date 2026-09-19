"""Derive checkable ground truth from the recorded SEC filings.

The golden dataset's hand-researched figures are correct but almost entirely
unverifiable against this system: the prompts ask for segment revenue, net
interest income, Intelligent Cloud margin, while the pipeline answers every
question with the same five ratios. Only one researched key - a debt-to-equity
ratio - overlapped, so faithfulness was being measured across 7 of 155 figures.

This script **adds** the five metrics the pipeline emits, computed from the
recorded filings, without removing anything. That choice matters:

* Adding them makes the figures the system does state verifiable, which is
  what faithfulness is supposed to measure.
* Not removing the researched figures keeps coverage honest. Coverage stays
  well below 100% precisely because the system answers a generic question
  rather than the one asked, and deleting the evidence of that would be
  scoring ourselves against a target we had already hit.

The arithmetic here is written out longhand rather than calling
:class:`FinancialCalculator`, so the dataset is an independent oracle for the
formulas - including the places they are easy to get wrong, such as the sign
and scale of a basis-point change.

    python scripts/build_golden_ground_truth.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "datasets" / "golden_evaluation_dataset.json"
FIXTURES = REPO / "datasets" / "sec_fixtures_fy2024.json"

# The metric names the synthesis step emits. Ground truth must use exactly
# these keys or the comparison silently checks nothing.
PIPELINE_METRICS = (
    "yoy_revenue_growth_pct",
    "operating_margin_current_pct",
    "operating_margin_compression_bps",
    "free_cash_flow_conversion_pct",
    "debt_to_equity_ratio",
)


def derive(current: dict[str, float], prior: dict[str, float]) -> dict[str, float]:
    """Compute the pipeline's metrics from raw XBRL facts.

    A metric is omitted when the registrant did not tag its inputs. That is not
    a gap to paper over: banks do not report an operating income line at all,
    so an operating margin for JPMorgan would be an invention, and asserting
    one as ground truth would penalise the system for correctly declining to
    produce it.
    """
    figures: dict[str, float] = {}

    rev_c, rev_p = current.get("revenue"), prior.get("revenue")
    if rev_c and rev_p:
        figures["yoy_revenue_growth_pct"] = round((rev_c - rev_p) / rev_p * 100, 2)

    op_c, op_p = current.get("operating_income"), prior.get("operating_income")
    if rev_c and op_c is not None:
        margin_c = op_c / rev_c * 100
        figures["operating_margin_current_pct"] = round(margin_c, 2)
        if rev_p and op_p is not None:
            margin_p = op_p / rev_p * 100
            # Compression is prior minus current, so margin *expansion* is
            # negative. Unrounded margins: rounding first shifts this by a
            # basis point or two.
            figures["operating_margin_compression_bps"] = round((margin_p - margin_c) * 100, 1)

    cfo = current.get("cash_from_operations")
    capex = current.get("capital_expenditures")
    net_income = current.get("net_income")
    if cfo is not None and capex is not None and net_income:
        figures["free_cash_flow_conversion_pct"] = round((cfo - capex) / net_income * 100, 2)

    debt, equity = current.get("total_debt"), current.get("shareholders_equity")
    if debt is not None and equity:
        figures["debt_to_equity_ratio"] = round(debt / equity, 3)

    return figures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    scenarios: list[dict[str, Any]] = json.loads(DATASET.read_text(encoding="utf-8"))
    fixtures: dict[str, Any] = json.loads(FIXTURES.read_text(encoding="utf-8"))

    added = 0
    for scenario in scenarios:
        # Adversarial and out-of-scope scenarios assert no figures by design:
        # the correct behaviour is refusal, and any ground truth here would
        # reward answering.
        if scenario["archetype"] in ("adversarial_security", "out_of_scope"):
            continue

        record = fixtures.get(scenario["ticker"])
        if record is None:
            print(f"  no recorded filing for {scenario['ticker']} ({scenario['id']})")
            continue

        derived = derive(record["current"], record["prior"])
        figures = scenario.setdefault("ground_truth_figures", {})

        # Where a researched figure collides with a derived one, the derived
        # value wins - but loudly. Each is traceable to a named accession
        # number and the registrant's own XBRL tags, whereas the researched
        # figures carry no such provenance and four of them turned out to be
        # wrong for FY2024 (AbbVie's equity base, for instance, is $3.3bn, not
        # the ~$9bn a 7.21x debt-to-equity ratio implies). Overwriting silently
        # would be indistinguishable from tuning the test to match the code.
        corrections = [
            (k, figures[k], v)
            for k, v in derived.items()
            if k in figures and figures[k] != v
        ]
        new = [k for k in derived if k not in figures]
        figures.update(derived)
        added += len(new)

        missing = [m for m in PIPELINE_METRICS if m not in derived]
        note = f"  (not tagged: {', '.join(missing)})" if missing else ""
        print(f"  {scenario['id']:10} {scenario['ticker']:6} +{len(new)}{note}")
        for key, old, value in corrections:
            print(
                f"      CORRECTED {key}: {old} -> {value} "
                f"(per {record['accession_number']})"
            )

    checkable = sum(
        1
        for s in scenarios
        for k in s.get("ground_truth_figures", {})
        if k in PIPELINE_METRICS
    )
    total = sum(len(s.get("ground_truth_figures", {})) for s in scenarios)
    print(f"\nadded {added} figures; {checkable}/{total} ground-truth keys are now checkable")

    if args.dry_run:
        print("dry run: dataset not written")
        return

    DATASET.write_text(json.dumps(scenarios, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {DATASET.relative_to(REPO)}")


if __name__ == "__main__":
    main()
