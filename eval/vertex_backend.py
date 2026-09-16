"""Vertex AI Gen AI Evaluation Service backend.

The capstone specifies evaluation "using Vertex AI Gen AI Evaluation" (p.14).
Until now the harness used only hand-rolled deterministic scorers, which is not
the named service. This module adds it as an **opt-in second backend** rather
than a replacement, because the two answer different questions:

================  ==========================================================
``local``         Deterministic, hermetic, free, instant. Answers "does the
                  number match ground truth?" - an exact-comparison question
                  that an LLM judge would answer *worse*, not better.
``vertex``        LLM-as-judge via Google's managed service. Answers "is this
                  prose actually supported by the cited evidence?" - which no
                  amount of float comparison can assess.
================  ==========================================================

`local` stays the CI default. A regression gate that makes billable network
calls to a judge model is slow, costs money per commit, and is
non-deterministic - the same commit can pass and then fail. `vertex` is for
periodic quality review, run deliberately.

Usage::

    python -m eval.evaluate_golden_dataset --backend=vertex --project=adis-workshop

Requires ``google-cloud-aiplatform[evaluation]`` and application-default
credentials with the Vertex AI User role.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

# Pointwise metrics from the managed service. Deliberately a short list:
#
#   groundedness              - the one that matters. Is every claim supported
#                               by the provided context? This is the metric the
#                               local backend genuinely cannot compute, since
#                               it requires reading prose against sources.
#   question_answering_quality - did the brief answer what was actually asked?
#   text_quality               - is it readable as analyst output?
#
# Omitted on purpose: `safety` and `fluency` add per-call cost while telling us
# nothing actionable about a template-synthesised financial brief, and
# `instruction_following` overlaps almost entirely with question-answering
# quality here.
DEFAULT_METRICS = ("groundedness", "question_answering_quality", "text_quality")

# The judge never sees these archetypes: a blocked adversarial prompt has no
# response to grade, and sending one would score a correct refusal as a bad
# answer.
_EXCLUDED_ARCHETYPES = frozenset({"adversarial_security", "out_of_scope"})


class VertexBackendUnavailableError(RuntimeError):
    """Raised when the Vertex evaluation SDK or credentials are missing."""


def build_context(citations: list[dict[str, Any]], max_chars: int = 12000) -> str:
    """Assemble grounding context from a brief's citations.

    Groundedness is judged *against this string*, so it must contain the
    evidence the brief claims to rest on and nothing else. Passing the source
    filings wholesale would let the judge mark a claim "grounded" on text the
    system never actually cited - scoring the corpus rather than the citation
    trail, which is the opposite of what we want to verify.
    """
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


def build_eval_dataframe(scenario_records: list[dict[str, Any]]) -> pd.DataFrame:
    """Shape executed scenarios into the service's expected column contract.

    The service requires `prompt`, `response` and (for groundedness) `context`.
    Rows whose response or context is empty are dropped rather than sent: the
    judge would score an empty string as ungrounded, which is true but
    uninformative, and it would drag the mean down for a reason unrelated to
    output quality. The count of dropped rows is returned to the caller via
    `run_vertex_evaluation` so the omission is visible rather than silent.
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise VertexBackendUnavailableError(
            "pandas is required for the Vertex backend. "
            'Install with: pip install "google-cloud-aiplatform[evaluation]"'
        ) from exc

    rows = []
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

    return pd.DataFrame(rows)


def run_vertex_evaluation(
    scenario_records: list[dict[str, Any]],
    project: str,
    location: str = "us-central1",
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    experiment: str | None = None,
) -> dict[str, Any]:
    """Score executed scenarios with the Vertex AI Gen AI Evaluation Service.

    Imports are deferred to call time. `google-cloud-aiplatform[evaluation]`
    pulls in pandas, tqdm and the full aiplatform stack; importing that at
    module scope would slow down - and could break - the default `local` path
    that most runs use and that CI depends on.
    """
    try:
        import vertexai
        from vertexai.preview.evaluation import EvalTask
    except ImportError as exc:
        raise VertexBackendUnavailableError(
            "The Vertex evaluation SDK is not installed. "
            'Install with: pip install "google-cloud-aiplatform[evaluation]"'
        ) from exc

    dataset = build_eval_dataframe(scenario_records)
    eligible = sum(1 for r in scenario_records if r.get("archetype") not in _EXCLUDED_ARCHETYPES)
    dropped = eligible - len(dataset)

    if dataset.empty:
        raise VertexBackendUnavailableError(
            "No scenario produced both a response and citation-derived context, "
            "so there is nothing for the judge to score. Check that the pipeline "
            "ran and that citations carry verbatim_quote values."
        )

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
        # Kept so a low aggregate can be traced to the scenarios that caused it.
        # An aggregate alone tells you something is wrong but not where.
        "per_scenario": result.metrics_table.to_dict(orient="records"),
    }


def _as_float(value: Any) -> Any:
    """Coerce numpy scalars to plain floats so the summary is JSON-serialisable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return value
