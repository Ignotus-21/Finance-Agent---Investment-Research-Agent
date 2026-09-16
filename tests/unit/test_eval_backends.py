"""Tests for the coverage-aware faithfulness metric and the Vertex eval backend.

The faithfulness tests exist because this metric was a hardcoded `1.0` for the
project's entire history while `compute_faithfulness` sat uncalled. The cases
below pin the distinction that absence made impossible: "verified correct",
"verified wrong", and "could not verify" must be three different outcomes.
"""

from __future__ import annotations

import pytest

from eval.metrics import EvaluationMetrics
from eval.regression_gate import _check_coverage_floor, check_thresholds
from eval.vertex_backend import (
    VertexBackendUnavailableError,
    build_context,
    build_eval_dataframe,
    run_vertex_evaluation,
)

cfc = EvaluationMetrics.compute_faithfulness_with_coverage


class TestFaithfulnessCoverage:
    def test_all_figures_present_and_correct(self):
        score, checked, expected = cfc({"revenue": 100.0, "eps": 2.5}, {"revenue": 100.0, "eps": 2.5})
        assert (score, checked, expected) == (1.0, 2, 2)

    def test_present_but_wrong_scores_zero_not_unmeasured(self):
        """A wrong answer is a failure, not a gap in coverage."""
        score, checked, expected = cfc({"revenue": 50.0}, {"revenue": 100.0})
        assert score == 0.0
        assert checked == 1

    def test_nothing_emitted_is_unmeasured_not_perfect(self):
        """The regression this whole module exists to prevent.

        The system emitted none of the asserted figures. That is an absence of
        evidence and must be `None` - scoring it 1.0 is what let a fabricated
        perfect groundedness score survive in CI.
        """
        score, checked, expected = cfc({"some_other_metric": 1.0}, {"revenue": 100.0})
        assert score is None
        assert (checked, expected) == (0, 1)

    def test_partial_coverage_scores_only_what_was_checked(self):
        """Coverage and correctness are reported independently."""
        score, checked, expected = cfc(
            {"revenue": 100.0}, {"revenue": 100.0, "eps": 2.5, "debt": 5.0}
        )
        assert score == 1.0  # the one figure checked was right
        assert (checked, expected) == (1, 3)  # but only 1 of 3 was checkable

    def test_no_ground_truth_is_vacuously_faithful(self):
        """Adversarial scenarios assert no figures, so nothing can be unfaithful."""
        assert cfc({}, {}) == (1.0, 0, 0)

    def test_relative_tolerance_accepts_rounding(self):
        score, _, _ = cfc({"revenue": 391.0}, {"revenue": 391.035})
        assert score == 1.0

    def test_relative_tolerance_rejects_a_real_discrepancy(self):
        """0.429 vs 0.701 is the actual PFE debt-to-equity mismatch found in
        the golden dataset. It must not be tolerated away."""
        score, _, _ = cfc({"debt_to_equity_ratio": 0.429}, {"debt_to_equity_ratio": 0.701})
        assert score == 0.0

    def test_collapsed_helper_treats_unverifiable_as_zero(self):
        """The single-float wrapper must not inherit the old 1.0 default."""
        assert EvaluationMetrics.compute_faithfulness({"other": 1.0}, {"revenue": 100.0}) == 0.0


def _summary(faith, coverage, *, enforce=True):
    return {
        "metrics_summary": {
            "mean_faithfulness": faith,
            "faithfulness_figure_coverage": coverage,
            "faithfulness_figures_checked": 7,
            "faithfulness_figures_expected": 155,
            "faithfulness_unmeasured_scenarios": 37,
            "mean_relevance": 1.0,
            "mean_citation_precision": 1.0,
            "guardrail_interception_rate": 1.0,
            "p95_latency_seconds": 0.25,
        },
        "target_thresholds": {
            "target_faithfulness": 1.0,
            "target_faithfulness_figure_coverage": 0.0,
            "enforce_faithfulness": enforce,
            "target_relevance": 0.90,
            "target_citation_precision": 1.0,
            "target_guardrail_rate": 1.0,
            "target_p95_latency_seconds": 60.0,
        },
    }


class TestRegressionGate:
    def test_failing_faithfulness_blocks_when_enforced(self):
        passed, waived = check_thresholds(_summary(0.6, 0.045, enforce=True))
        assert passed is False
        assert waived == []

    def test_failing_faithfulness_is_waived_but_still_reported(self, capsys):
        """The waiver suspends the exit code, never the reported number."""
        passed, waived = check_thresholds(_summary(0.6, 0.045, enforce=False))
        assert passed is True
        assert waived == ["faithfulness"]

        out = capsys.readouterr().out
        assert "0.6000" in out, "the real score must still be printed"
        assert "FAILED" in out
        assert "WAIVED" in out

    def test_unmeasured_faithfulness_is_not_printed_as_a_pass(self, capsys):
        check_thresholds(_summary(None, 0.0, enforce=False))
        out = capsys.readouterr().out
        assert "UNMEASURED" in out
        assert "PASSED: Faithfulness" not in out

    def test_coverage_regression_fails_the_floor(self):
        """Measuring less must not be a way to score higher."""
        targets = {"target_faithfulness_figure_coverage": 0.30}
        assert _check_coverage_floor(0.20, targets) is False
        assert _check_coverage_floor(0.30, targets) is True


class TestVertexBackend:
    def test_context_is_built_only_from_cited_quotes(self):
        """Groundedness must be judged against what was cited, nothing more."""
        context = build_context([
            {
                "source_type": "SEC_FORM_10K",
                "filing_accession_number": "0000320193-24-000106",
                "table_or_section_name": "Income Statement",
                "verbatim_quote": "Total net sales were $391,035 million.",
            },
            {"source_type": "SEC_FORM_10K", "verbatim_quote": ""},  # dropped
        ])
        assert "391,035" in context
        assert "0000320193-24-000106" in context
        assert context.count("[") == 1, "the empty-quote citation must not appear"

    def test_context_is_truncated(self):
        long_quote = [{"source_type": "X", "verbatim_quote": "y" * 50_000}]
        assert len(build_context(long_quote, max_chars=100)) == 100

    def test_adversarial_scenarios_are_excluded_from_the_judge(self):
        """A blocked prompt has no answer; grading it would penalise a correct refusal."""
        df = build_eval_dataframe([
            {"id": "a", "archetype": "adversarial_security", "prompt": "p", "response": "r", "context": "c"},
            {"id": "b", "archetype": "out_of_scope", "prompt": "p", "response": "r", "context": "c"},
            {"id": "c", "archetype": "standard_extraction", "prompt": "p", "response": "r", "context": "c"},
        ])
        assert list(df["scenario_id"]) == ["c"]

    def test_rows_without_response_or_context_are_dropped(self):
        df = build_eval_dataframe([
            {"id": "a", "archetype": "standard_extraction", "prompt": "p", "response": "", "context": "c"},
            {"id": "b", "archetype": "standard_extraction", "prompt": "p", "response": "r", "context": ""},
            {"id": "c", "archetype": "standard_extraction", "prompt": "p", "response": "r", "context": "c"},
        ])
        assert list(df["scenario_id"]) == ["c"]

    def test_empty_dataset_raises_rather_than_submitting(self):
        """Never bill for a request that cannot produce a meaningful score."""
        with pytest.raises(VertexBackendUnavailableError, match="nothing for the judge"):
            run_vertex_evaluation(
                [{"id": "a", "archetype": "adversarial_security", "prompt": "p", "response": "r", "context": "c"}],
                project="test-project",
            )
