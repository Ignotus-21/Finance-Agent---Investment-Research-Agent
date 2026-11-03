"""
Vertex AI Gen AI Evaluation Service Backend.
Supports LLM-as-judge evaluation (`groundedness`, `question_answering_quality`,
`text_quality`) via Google Cloud Vertex AI alongside the deterministic local
regression gate (`--backend=local` or `--backend=vertex`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

DEFAULT_METRICS = ("groundedness", "question_answering_quality", "text_quality")
_EXCLUDED_ARCHETYPES = frozenset({"adversarial_security", "out_of_scope"})


class VertexBackendUnavailableError(RuntimeError):
    """Raised when the Vertex evaluation SDK or credentials are missing."""


def build_context(citations: list[dict[str, Any]], max_chars: int = 12000) -> str:
    """Assemble grounding context string from a brief's primary-source citations."""
    parts: list[str] = []
    for c in citations:
        quote = (c.get("verbatim_quote") or "").strip()
        if not quote:
            continue
        label = " ".join(
            str(x)
            for x in (
                c.get("source_type"),
                c.get("filing_accession_number"),
                c.get("table_or_section_name"),
                c.get("row_item"),
            )
            if x
        )
        parts.append(f"[{label}]\n{quote}")

    context = "\n\n".join(parts)
    return context[:max_chars]


def select_judge_rows(scenario_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter executed scenarios to in-scope rows with non-empty response and context."""
    rows: list[dict[str, Any]] = []
    for rec in scenario_records:
        if rec.get("archetype") in _EXCLUDED_ARCHETYPES:
            continue
        response = (rec.get("response") or "").strip()
        context = (rec.get("context") or "").strip()
        if not response or not context:
            continue
        rows.append(
            {
                "scenario_id": rec["id"],
                "prompt": rec["prompt"],
                "response": response,
                "context": context,
                "reference": rec.get("reference", ""),
            }
        )
    return rows


def build_eval_dataframe(scenario_records: list[dict[str, Any]]) -> pd.DataFrame:
    """Shape selected scenarios into the Vertex Evaluation Service DataFrame contract."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise VertexBackendUnavailableError(
            "pandas is required for the Vertex backend. "
            'Install with: pip install "google-cloud-aiplatform[evaluation]"'
        ) from exc

    return pd.DataFrame(select_judge_rows(scenario_records))


def run_vertex_evaluation(
    scenario_records: list[dict[str, Any]],
    project: str,
    location: str = "us-central1",
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    experiment: str | None = None,
) -> dict[str, Any]:
    """Score executed scenarios with the Vertex AI Gen AI Evaluation Service."""
    rows = select_judge_rows(scenario_records)
    eligible = sum(1 for r in scenario_records if r.get("archetype") not in _EXCLUDED_ARCHETYPES)
    dropped = eligible - len(rows)

    if not rows:
        raise VertexBackendUnavailableError(
            "No scenario produced both a response and citation-derived context, "
            "so there is nothing for the judge to score. Check that the pipeline "
            "ran and that citations carry verbatim_quote values."
        )

    try:
        import vertexai
        from vertexai.preview.evaluation import EvalTask
    except ImportError as exc:
        raise VertexBackendUnavailableError(
            "The Vertex evaluation SDK is not installed. "
            'Install with: pip install "google-cloud-aiplatform[evaluation]"'
        ) from exc

    dataset = build_eval_dataframe(scenario_records)

    vertexai.init(project=project, location=location)

    task = EvalTask(
        dataset=dataset,
        metrics=list(metrics),
        experiment=experiment,
    )
    result = task.evaluate()

    summary = {k: _as_float(v) for k, v in dict(result.summary_metrics).items()}

    return {
        "backend": "vertex",
        "service": "Vertex AI Gen AI Evaluation",
        "project": project,
        "location": location,
        "metrics_requested": list(metrics),
        "rows_scored": int(len(dataset)),
        "rows_dropped_no_response_or_context": int(dropped),
        "rows_excluded_adversarial": len(scenario_records) - eligible,
        "summary_metrics": summary,
        "per_scenario": result.metrics_table.to_dict(orient="records"),
    }


def _as_float(value: Any) -> Any:
    """Coerce numpy scalars to plain floats for JSON serialization."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return value
