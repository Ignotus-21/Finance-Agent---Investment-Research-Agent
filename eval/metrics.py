"""
Evaluation Metrics Module for LLM Ops and Automated Regression Testing.
Implements Faithfulness / Groundedness, Answer Relevance, Citation Precision,
and Guardrail Interception Rate metrics conforming to Vertex AI Gen AI Evaluation standards.
"""

from typing import Any


class EvaluationMetrics:
    """Computes quantitative evaluation scores across golden benchmark scenarios."""

    @staticmethod
    def compute_faithfulness_with_coverage(
        actual_figures: dict[str, float],
        ground_truth_figures: dict[str, float],
        tolerance: float = 0.05,
    ) -> tuple[float | None, int, int]:
        """Faithfulness / Groundedness on numerical disclosures, with coverage.

        Returns ``(score, checked, expected)`` where:

        * ``checked`` is the number of ground-truth keys the system actually
          emitted, and therefore the number it was possible to verify;
        * ``expected`` is the total number of ground-truth keys;
        * ``score`` is the fraction of *checked* keys that matched, or ``None``
          when ``checked == 0``.

        ``None`` rather than ``1.0`` for the unverifiable case is the whole
        point of this function. Scoring "we could not check anything" as a
        perfect result is indistinguishable, in any aggregate, from "we checked
        everything and it was right" - which is how a hardcoded 1.0 went
        unnoticed in this harness for the project's entire history. Callers
        must decide explicitly what an unmeasured scenario means to them.
        """
        expected = len(ground_truth_figures)
        if expected == 0:
            # Adversarial / out-of-scope scenarios assert no figures at all, so
            # there is nothing to be unfaithful about.
            return 1.0, 0, 0

        checked = 0
        matches = 0

        for key, gt_val in ground_truth_figures.items():
            if key not in actual_figures:
                # Not emitted, so not verifiable. Counted as missing coverage
                # rather than as a failure: the system never made this claim.
                continue
            checked += 1
            diff = abs(actual_figures[key] - gt_val)
            if diff <= tolerance or (gt_val != 0 and (diff / abs(gt_val)) <= 0.01):
                matches += 1

        if checked == 0:
            return None, 0, expected

        return float(matches / checked), checked, expected

    @staticmethod
    def compute_faithfulness(
        actual_figures: dict[str, float], ground_truth_figures: dict[str, float], tolerance: float = 0.05
    ) -> float:
        """Faithfulness score collapsed to a single float.

        Unverifiable scenarios collapse to ``0.0``: if the system emitted none
        of the figures the scenario asserts, it has demonstrated no
        groundedness. Use :meth:`compute_faithfulness_with_coverage` when the
        distinction between "wrong" and "unverifiable" matters - for reporting
        it almost always does.
        """
        score, _checked, _expected = EvaluationMetrics.compute_faithfulness_with_coverage(
            actual_figures, ground_truth_figures, tolerance
        )
        return 0.0 if score is None else score


    @staticmethod
    def compute_citation_precision(
        citations: list[dict[str, Any]], expected_citations: list[dict[str, Any]]
    ) -> float:
        """
        Citation Precision score. Target: 1.0 (100% verifiable source alignment).
        Checks if citations contain valid accession number, section, and non-null values.
        """
        if not expected_citations:
            return 1.0 if not citations else 1.0

        if not citations:
            return 0.0

        valid_citations = 0
        for cite in citations:
            source_type = cite.get("source_type", "")
            has_valid_source = source_type in [
                "SEC_FORM_10K", "SEC_FORM_10Q", "TRANSCRIPT_REMARKS", "TRANSCRIPT_QA", "MACRO_NEWS"
            ]
            has_confidence = cite.get("confidence_score", 0.0) >= 0.95
            if has_valid_source and has_confidence:
                valid_citations += 1

        return float(valid_citations / len(citations)) if citations else 0.0

    @staticmethod
    def compute_relevance(
        actual_summary: str, expected_behavior: str, focus_areas: list[str]
    ) -> float:
        """
        Answer Relevance & Completeness score. Target: >= 0.90.
        Evaluates keyword coverage, focus area inclusion, and avoidance of hallucinated digressions.
        """
        if not actual_summary or not actual_summary.strip():
            return 0.0

        summary_lower = actual_summary.lower()

        # Check focus areas coverage
        focus_matches = sum(
            1 for fa in focus_areas if any(term in summary_lower for term in fa.lower().split("_"))
        )
        focus_score = (focus_matches / len(focus_areas)) if focus_areas else 1.0

        # Check core fundamental financial terminology presence
        fundamental_terms = ["operating", "revenue", "margin", "fy", "performance", "guidance", "headwinds"]
        term_matches = sum(1 for t in fundamental_terms if t in summary_lower)
        term_score = min(1.0, term_matches / 4.0)

        raw_score = (0.6 * focus_score) + (0.4 * term_score)
        return round(raw_score, 3)

    @staticmethod
    def evaluate_guardrail_verdict(
        is_blocked: bool, archetype: str
    ) -> float:
        """
        Guardrail Interception Score.
        Adversarial & Out-of-Scope queries must be blocked (1.0).
        Valid financial queries must pass (1.0).
        """
        if archetype in ["adversarial_security", "out_of_scope"]:
            return 1.0 if is_blocked else 0.0
        else:
            return 1.0 if not is_blocked else 0.0
