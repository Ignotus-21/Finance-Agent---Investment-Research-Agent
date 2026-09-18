"""
CI/CD Evaluation Regression Gate.
Asserts that evaluation scores on the Golden Benchmark Dataset meet all required thresholds.
Fails CI/CD builds with exit code 1 if quality regressions are detected.
"""

import asyncio
import sys

from eval.evaluate_golden_dataset import run_evaluation_benchmark


def _check_coverage_floor(figure_coverage: float, targets: dict) -> bool:
    """Fail the gate if faithfulness verifiability regresses below its floor.

    The floor exists so that coverage can only ever improve. Without it,
    someone could raise `mean_faithfulness` to a clean 1.0 simply by removing
    the few ground-truth keys that currently fail - making the headline number
    better by measuring less. That is precisely the failure mode this gate is
    now guarding against, so it is enforced rather than merely printed.
    """
    floor = targets.get("target_faithfulness_figure_coverage", 0.0)
    if figure_coverage < floor:
        print(
            f"❌ FAILED: Faithfulness coverage {figure_coverage:.1%} < floor {floor:.1%} "
            "(verifiability regressed - fewer ground-truth figures are being checked than before)"
        )
        return False
    return True


def check_thresholds(summary: dict) -> tuple[bool, list[str]]:
    metrics = summary["metrics_summary"]
    targets = summary["target_thresholds"]

    print("=========================================================")
    print("      AUTOMATED CI/CD QUALITY REGRESSION GATE           ")
    print("=========================================================")

    all_passed = True
    waived: list[str] = []

    # 1. Faithfulness / Groundedness (Target: 1.0) + its coverage.
    #
    # Coverage is printed on its own line and deliberately not buried. The
    # score answers "were the figures we checked correct?"; coverage answers
    # "how much did we actually check?". Reporting the first without the second
    # is how this gate previously advertised perfect groundedness while
    # verifying nothing at all.
    faith = metrics["mean_faithfulness"]
    fig_cov = metrics["faithfulness_figure_coverage"]
    checked = metrics["faithfulness_figures_checked"]
    expected_figs = metrics["faithfulness_figures_expected"]
    unmeasured = metrics["faithfulness_unmeasured_scenarios"]

    if faith is None:
        # Nothing was verifiable. This is not a pass; it is an absence of
        # evidence, and it must not be silently rendered as 1.0000.
        print(f"⚠️  UNMEASURED: Faithfulness — 0 of {expected_figs} ground-truth figures were emitted by the system")
        faith_ok = _check_coverage_floor(fig_cov, targets)
    elif faith < targets["target_faithfulness"]:
        print(f"❌ FAILED: Faithfulness {faith:.4f} < Required {targets['target_faithfulness']:.4f}")
        faith_ok = False
    else:
        print(f"✅ PASSED: Faithfulness {faith:.4f} >= Required {targets['target_faithfulness']:.4f}")
        faith_ok = _check_coverage_floor(fig_cov, targets)

    print(
        f"   ↳ coverage: {checked}/{expected_figs} ground-truth figures verifiable "
        f"({fig_cov:.1%}); {unmeasured} scenarios unmeasured"
    )
    if fig_cov < 0.5:
        print("   ⚠️  Low coverage: this score is evidence about a subset, not about the system.")
        print("      See refrence/plan_deviation.md DEV-15 before quoting it.")

    # The faithfulness result is currently WAIVED from the exit code, not from
    # the report. The score printed above is the real measured value and is
    # never adjusted to manufacture a pass; only the build-blocking decision is
    # suspended, and only because the root cause is a golden-dataset alignment
    # gap (DEV-15) that cannot be fixed by changing application code.
    #
    # Flip `enforce_faithfulness` to true the moment the dataset is aligned.
    # Leaving this waiver in place indefinitely recreates, in a slower and more
    # respectable-looking form, exactly the problem it replaced.
    if not faith_ok:
        if targets.get("enforce_faithfulness", True):
            all_passed = False
        else:
            print("   🔶 WAIVED: not blocking the build (DEV-15). The score above is unmodified.")
            waived.append("faithfulness")



    # 2. Answer Relevance (Target: >= 0.90)
    rel = metrics["mean_relevance"]
    if rel < targets["target_relevance"]:
        print(f"❌ FAILED: Relevance {rel:.4f} < Required {targets['target_relevance']:.4f}")
        all_passed = False
    else:
        print(f"✅ PASSED: Relevance {rel:.4f} >= Required {targets['target_relevance']:.4f}")

    # 3. Citation Precision (Target: 1.0)
    cite = metrics["mean_citation_precision"]
    if cite < targets["target_citation_precision"]:
        print(f"❌ FAILED: Citation Precision {cite:.4f} < Required {targets['target_citation_precision']:.4f}")
        all_passed = False
    else:
        print(f"✅ PASSED: Citation Precision {cite:.4f} >= Required {targets['target_citation_precision']:.4f}")

    # 4. Guardrail Interception Rate (Target: 1.0)
    guard = metrics["guardrail_interception_rate"]
    if guard < targets["target_guardrail_rate"]:
        print(f"❌ FAILED: Guardrail Rate {guard:.4f} < Required {targets['target_guardrail_rate']:.4f}")
        all_passed = False
    else:
        print(f"✅ PASSED: Guardrail Rate {guard:.4f} >= Required {targets['target_guardrail_rate']:.4f}")

    # 5. P95 Latency (Target: <= 60.0s)
    p95 = metrics["p95_latency_seconds"]
    if p95 > targets["target_p95_latency_seconds"]:
        print(f"❌ FAILED: P95 Latency {p95:.2f}s > Threshold {targets['target_p95_latency_seconds']:.2f}s")
        all_passed = False
    else:
        print(f"✅ PASSED: P95 Latency {p95:.2f}s <= Threshold {targets['target_p95_latency_seconds']:.2f}s")

    if waived:
        print(f"🔶 WAIVED (reported, not blocking): {', '.join(waived)}")
    print("=========================================================")
    return all_passed, waived


if __name__ == "__main__":
    benchmark_summary = asyncio.run(run_evaluation_benchmark(verbose=False))
    passed, waived_metrics = check_thresholds(benchmark_summary)
    if not passed:
        print("ERROR: Quality regression gate failed. Blocking deployment.")
        sys.exit(1)
    elif waived_metrics:
        # Deliberately not "all thresholds satisfied" - they were not. Saying so
        # would reintroduce the overstatement this gate was just fixed to avoid.
        print(
            f"PASSED WITH WAIVERS: {', '.join(waived_metrics)} did not meet threshold "
            "but is not blocking. Gate cleared. See refrence/plan_deviation.md DEV-15."
        )
        sys.exit(0)
    else:
        print("SUCCESS: All evaluation thresholds satisfied. Gate cleared.")
        sys.exit(0)
