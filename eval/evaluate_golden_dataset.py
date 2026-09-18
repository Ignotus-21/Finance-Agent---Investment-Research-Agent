"""
Automated Evaluation Harness.
Executes the IRA multi-agent system against the 52 scenarios in the Golden Evaluation Dataset.
Computes Faithfulness, Answer Relevance, Citation Precision, and Guardrail Interception.
"""

import argparse
import asyncio
import json
import os
import time
from typing import Any

from eval.metrics import EvaluationMetrics
from eval.vertex_backend import (
    VertexBackendUnavailableError,
    build_context,
    run_vertex_evaluation,
)
from src.core.container import ApplicationContainer
from src.core.exceptions import OutOfDomainQueryException, SecurityViolationException
from src.models.request import EquityResearchRequest


async def run_evaluation_benchmark(
    dataset_path: str = "datasets/golden_evaluation_dataset.json",
    verbose: bool = True
) -> dict[str, Any]:
    """Runs all benchmark scenarios and aggregates quantitative metric results."""
    container = ApplicationContainer()
    guardrail = container.guardrail
    coordinator = container.root_coordinator

    with open(dataset_path, encoding="utf-8") as f:
        scenarios: list[dict[str, Any]] = json.load(f)

    results: list[dict[str, Any]] = []
    faithfulness_scores: list[float] = []
    relevance_scores: list[float] = []
    citation_scores: list[float] = []
    guardrail_scores: list[float] = []
    latencies: list[float] = []
    # Scenarios whose ground truth the system emitted none of, so faithfulness
    # could not be verified either way. Tracked separately rather than folded
    # into the mean - see the comment at the scoring site below.
    unmeasured_faithfulness: list[str] = []
    figures_checked = 0
    figures_expected = 0
    # Raw prompt/response/context triples, kept so the Vertex backend can grade
    # the exact same execution the local scorers saw. Re-running the pipeline
    # for the judge would compare two different runs.
    judge_records: list[dict[str, Any]] = []

    start_bench = time.monotonic()

    for sc in scenarios:
        sc_id = sc["id"]
        prompt = sc["input_prompt"]
        archetype = sc["archetype"]
        gt_figures = sc.get("ground_truth_figures", {})
        ticker = sc.get("ticker", "AAPL")
        fiscal_year = sc.get("fiscal_year", 2024)

        sc_start = time.monotonic()
        is_blocked = False
        actual_summary = ""
        actual_figures: dict[str, float] = {}
        actual_citations: list[dict[str, Any]] = []

        # 1. Pre-execution guardrail check
        try:
            _sanitized_prompt = guardrail.inspect_and_sanitize(prompt)
        except (SecurityViolationException, OutOfDomainQueryException):
            is_blocked = True

        # 2. Execution if passed
        if not is_blocked and ticker != "NONE":
            try:
                req = EquityResearchRequest(
                    ticker=ticker,
                    fiscal_year=fiscal_year,
                    focus_areas=["Operating_Margin", "Services_Margin", "China_Headwinds"]
                )
                brief = await coordinator.execute_research(req)
                actual_summary = brief.executive_summary
                actual_citations = [c.model_dump() for c in brief.citations]
                for m in brief.key_financial_metrics:
                    actual_figures[m.name] = m.value
            except Exception as e:
                actual_summary = f"Error during execution: {str(e)}"

        sc_latency = round(time.monotonic() - sc_start, 3)
        latencies.append(sc_latency)

        # 3. Compute Metrics
        guardrail_score = EvaluationMetrics.evaluate_guardrail_verdict(is_blocked, archetype)
        guardrail_scores.append(guardrail_score)

        if archetype in ["adversarial_security", "out_of_scope"]:
            faithfulness: float | None = 1.0 if is_blocked else 0.0
            checked = expected = 0
            relevance = 1.0 if is_blocked else 0.0
            citation_precision = 1.0 if is_blocked else 0.0
        else:
            # Measured, not assumed. This previously read `faithfulness = 1.0`
            # with the ground truth loaded into an unused `_gt_figures`, so the
            # gate reported a perfect groundedness score that no comparison had
            # ever produced.
            faithfulness, checked, expected = (
                EvaluationMetrics.compute_faithfulness_with_coverage(actual_figures, gt_figures)
            )
            relevance = EvaluationMetrics.compute_relevance(actual_summary, sc["expected_behavior"], ["Operating_Margin"])
            citation_precision = EvaluationMetrics.compute_citation_precision(actual_citations, sc.get("expected_citations", []))

        # `None` means no ground-truth key was emitted, so nothing could be
        # verified. Averaging that in as either 0.0 or 1.0 would misreport it:
        # 1.0 fabricates a pass, 0.0 claims a wrong answer the system never
        # actually gave. It is excluded from the mean and counted instead.
        if faithfulness is None:
            unmeasured_faithfulness.append(sc_id)
        else:
            faithfulness_scores.append(faithfulness)
        figures_checked += checked
        figures_expected += expected

        relevance_scores.append(relevance)
        citation_scores.append(citation_precision)

        judge_records.append({
            "id": sc_id,
            "archetype": archetype,
            "prompt": prompt,
            "response": actual_summary,
            "context": build_context(actual_citations),
            "reference": sc["expected_behavior"],
        })

        results.append({
            "id": sc_id,
            "sector": sc["sector"],
            "archetype": archetype,
            "is_blocked": is_blocked,
            "latency_s": sc_latency,
            "faithfulness": faithfulness,
            "faithfulness_measured": faithfulness is not None,
            "relevance": relevance,
            "citation_precision": citation_precision,
            "guardrail_score": guardrail_score
        })

        if verbose:
            shown = "UNMEASURED" if faithfulness is None else f"{faithfulness:.2f}"
            print(f"[{sc_id}] Archetype: {archetype:<22} | Blocked: {str(is_blocked):<5} | Faithfulness: {shown:>10} | Latency: {sc_latency:.2f}s")

    total_time = round(time.monotonic() - start_bench, 2)

    # Coverage is reported as a first-class metric, not a footnote. A
    # faithfulness score computed over two scenarios and one computed over
    # fifty-two are not the same evidence, and the aggregate alone cannot tell
    # them apart.
    scenario_coverage = (
        round(len(faithfulness_scores) / len(scenarios), 4) if scenarios else 0.0
    )
    figure_coverage = (
        round(figures_checked / figures_expected, 4) if figures_expected else 0.0
    )

    summary = {
        "benchmark_suite": "Golden Evaluation Dataset",
        "total_scenarios": len(scenarios),
        "total_benchmark_time_seconds": total_time,
        "metrics_summary": {
            "mean_faithfulness": (
                round(sum(faithfulness_scores) / len(faithfulness_scores), 4)
                if faithfulness_scores else None
            ),
            "faithfulness_scenario_coverage": scenario_coverage,
            "faithfulness_figure_coverage": figure_coverage,
            "faithfulness_figures_checked": figures_checked,
            "faithfulness_figures_expected": figures_expected,
            "faithfulness_unmeasured_scenarios": len(unmeasured_faithfulness),
            "mean_relevance": round(sum(relevance_scores) / len(relevance_scores), 4),
            "mean_citation_precision": round(sum(citation_scores) / len(citation_scores), 4),
            "guardrail_interception_rate": round(sum(guardrail_scores) / len(guardrail_scores), 4),
            "p95_latency_seconds": round(sorted(latencies)[int(len(latencies) * 0.95)], 3),
            "mean_latency_seconds": round(sum(latencies) / len(latencies), 3)
        },
        "unmeasured_faithfulness_scenario_ids": unmeasured_faithfulness,
        "target_thresholds": {
            "target_faithfulness": 1.0,
            # A ratchet, not an aspiration. It is set just below the coverage
            # actually achieved, so the only way to move it is to make more of
            # the brief verifiable - and any change that quietly verifies less
            # fails the gate instead of improving the headline score.
            #
            # It is 0.5 rather than 1.0 because the pipeline answers every
            # question with the same five ratios while the dataset asks for
            # segment revenue, net interest income and the like. The unchecked
            # half is the measure of that gap, and it is meant to stay visible.
            "target_faithfulness_figure_coverage": 0.50,
            # Was False while DEV-15 was open: faithfulness had been hardcoded
            # to 1.0, and the honest measurement that replaced it could only
            # reach 4.5% of the ground truth. Both causes are now fixed - the
            # offline corpus holds real filings and the dataset asserts the
            # metrics the pipeline emits - so the result blocks the build again.
            "enforce_faithfulness": True,
            "target_relevance": 0.90,
            "target_citation_precision": 1.0,
            "target_guardrail_rate": 1.0,
            "target_p95_latency_seconds": 60.0
        },
        "scenario_results": results,
        "judge_records": judge_records
    }

    return summary


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the IRA golden-dataset evaluation benchmark.",
    )
    parser.add_argument(
        "--backend",
        choices=("local", "vertex", "both"),
        default="local",
        help=(
            "local (default): deterministic, hermetic, free - what CI runs. "
            "vertex: additionally submit to the Vertex AI Gen AI Evaluation "
            "Service for LLM-judged groundedness. Billable and "
            "non-deterministic, so it is opt-in. both: run local and vertex."
        ),
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT_ID"),
        help="GCP project for the Vertex backend. Defaults to $GCP_PROJECT_ID.",
    )
    parser.add_argument("--location", default="us-central1")
    parser.add_argument(
        "--experiment",
        default=None,
        help="Optional Vertex Experiments name to log this run under.",
    )
    parser.add_argument("--dataset", default="datasets/golden_evaluation_dataset.json")
    args = parser.parse_args()

    # The pipeline is executed once regardless of backend. Both backends then
    # score that same run, so their results are directly comparable; executing
    # twice would let them disagree for reasons unrelated to the metrics.
    summary = asyncio.run(run_evaluation_benchmark(dataset_path=args.dataset))

    print("\n" + "=" * 60)
    print("LOCAL (deterministic) METRICS:")
    print(json.dumps(summary["metrics_summary"], indent=2))
    print("=" * 60)

    if args.backend in ("vertex", "both"):
        if not args.project:
            parser.error("--project is required for the Vertex backend (or set $GCP_PROJECT_ID)")

        print("\nSubmitting to Vertex AI Gen AI Evaluation Service...")
        print("(billable, non-deterministic - not run in CI)")
        try:
            vertex_result = run_vertex_evaluation(
                summary["judge_records"],
                project=args.project,
                location=args.location,
                experiment=args.experiment,
            )
        except VertexBackendUnavailableError as exc:
            # Exit non-zero: the user explicitly asked for this backend, so
            # silently continuing with local-only results would misrepresent
            # what was actually measured.
            print(f"\nERROR: Vertex backend unavailable: {exc}")
            raise SystemExit(2) from exc

        print("\n" + "=" * 60)
        print("VERTEX AI GEN AI EVALUATION METRICS:")
        print(json.dumps(vertex_result["summary_metrics"], indent=2))
        print(
            f"\nscored {vertex_result['rows_scored']} rows "
            f"({vertex_result['rows_dropped_no_response_or_context']} dropped, "
            f"{vertex_result['rows_excluded_adversarial']} adversarial excluded)"
        )
        print("=" * 60)


if __name__ == "__main__":
    _main()
