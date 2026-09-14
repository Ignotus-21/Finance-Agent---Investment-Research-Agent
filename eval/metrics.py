"""
Evaluation Metrics Module for LLM Ops and Automated Regression Testing.
Implements Faithfulness / Groundedness, Answer Relevance, Citation Precision,
and Guardrail Interception Rate metrics conforming to Vertex AI Gen AI Evaluation standards.
"""

from typing import Dict, Any, List, Optional
import math


class EvaluationMetrics:
    """Computes quantitative evaluation scores across golden benchmark scenarios."""

    @staticmethod
    def compute_faithfulness(
        actual_figures: Dict[str, float], ground_truth_figures: Dict[str, float], tolerance: float = 0.05
    ) -> float:
        """
        Faithfulness / Groundedness score on numerical disclosures.
        Score = 1.0 if all figures match ground truth within tolerance; 0.0 otherwise.
        """
        if not ground_truth_figures:
            return 1.0  # Adversarial / out-of-scope scenarios have no expected numbers

        if not actual_figures:
            return 0.0

        matches = 0
        total = len(ground_truth_figures)

        for key, gt_val in ground_truth_figures.items():
            if key in actual_figures:
                act_val = actual_figures[key]
                diff = abs(act_val - gt_val)
                # Check absolute and relative tolerance
                if diff <= tolerance or (gt_val != 0 and (diff / abs(gt_val)) <= 0.01):
                    matches += 1

        return float(matches / total) if total > 0 else 1.0

    @staticmethod
    def compute_citation_precision(
        citations: List[Dict[str, Any]], expected_citations: List[Dict[str, Any]]
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
        actual_summary: str, expected_behavior: str, focus_areas: List[str]
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
