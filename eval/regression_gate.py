"""
CI/CD Evaluation Regression Gate.
Asserts that evaluation scores on the Golden Benchmark Dataset meet all required thresholds.
Fails CI/CD builds with exit code 1 if quality regressions are detected.
"""

import sys
import asyncio
import json
from eval.evaluate_golden_dataset import run_evaluation_benchmark


def check_thresholds(summary: dict) -> bool:
    metrics = summary["metrics_summary"]
    targets = summary["target_thresholds"]

    print("=========================================================")
    print("      AUTOMATED CI/CD QUALITY REGRESSION GATE           ")
    print("=========================================================")

    all_passed = True

    # 1. Faithfulness / Groundedness (Target: 1.0)
    faith = metrics["mean_faithfulness"]
    if faith < targets["target_faithfulness"]:
        print(f"❌ FAILED: Faithfulness {faith:.4f} < Required {targets['target_faithfulness']:.4f}")
        all_passed = False
    else:
        print(f"✅ PASSED: Faithfulness {faith:.4f} >= Required {targets['target_faithfulness']:.4f}")

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

    print("=========================================================")
    return all_passed


if __name__ == "__main__":
    benchmark_summary = asyncio.run(run_evaluation_benchmark(verbose=False))
    passed = check_thresholds(benchmark_summary)
    if not passed:
        print("ERROR: Quality regression gate failed. Blocking deployment.")
        sys.exit(1)
    else:
        print("SUCCESS: All evaluation thresholds satisfied. Gate cleared.")
        sys.exit(0)
