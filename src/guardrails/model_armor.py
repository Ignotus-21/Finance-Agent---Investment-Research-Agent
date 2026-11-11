"""
Model Armor screening.
Screens text against a Google Cloud Model Armor template at three stages of the
request lifecycle: the inbound user prompt (ingress), content returned by tools
and sub-agents (indirect prompt injection), and the outbound model response or
synthesised brief (egress).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

logger = logging.getLogger(__name__)


class ScreenStage(StrEnum):
    """Where in the lifecycle the text is being screened."""

    PROMPT = "prompt"
    TOOL_OUTPUT = "tool_output"
    RESPONSE = "response"


# Filters that cause a block at each stage. ``None`` means any filter match
# blocks. Retrieved filings and transcripts legitimately describe hazardous
# operations, litigation and adverse drug events, so Responsible-AI matches on
# tool output are logged but do not withhold the evidence; injection,
# malicious-URI, sensitive-data and CSAM matches do.
BLOCK_POLICY: dict[ScreenStage, frozenset[str] | None] = {
    ScreenStage.PROMPT: None,
    ScreenStage.TOOL_OUTPUT: frozenset({"pi_and_jailbreak", "malicious_uri", "sdp", "csam"}),
    ScreenStage.RESPONSE: None,
}


@dataclass(frozen=True)
class ModelArmorVerdict:
    """Outcome of a Model Armor screening call."""

    blocked: bool
    stage: str = ScreenStage.PROMPT.value
    matched_filters: tuple[str, ...] = ()
    degraded: bool = False
    detail: str = ""
    chunks: int = 1
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


class ModelArmorScreen:
    """
    Calls `SanitizeUserPrompt` (prompt and tool-output stages) or
    `SanitizeModelResponse` (response stage) on a Model Armor template and
    reduces the sanitization result to a block / allow verdict.

    `template` is the full resource name
    `projects/<project>/locations/<location>/templates/<template_id>`.
    Model Armor is a regional API; the client targets
    `modelarmor.<location>.rep.googleapis.com`. Text longer than
    `max_chunk_chars` is screened in sequential chunks so a single request stays
    under the service's per-request token limit.
    """

    FILTER_FIELDS: tuple[str, ...] = (
        "pi_and_jailbreak_filter_result",
        "rai_filter_result",
        "malicious_uri_filter_result",
        "sdp_filter_result",
        "csam_filter_filter_result",
        "virus_scan_filter_result",
    )

    def __init__(
        self,
        template: str,
        client: Any | None = None,
        timeout_seconds: float = 3.0,
        fail_closed: bool = False,
        max_chunk_chars: int = 100_000,
    ) -> None:
        if not template or template.count("/") < 5:
            raise ValueError(
                "MODEL_ARMOR_TEMPLATE must be a full resource name "
                "'projects/<project>/locations/<location>/templates/<id>'."
            )
        if max_chunk_chars < 1_000:
            raise ValueError("max_chunk_chars must be at least 1000.")
        self.template = template
        self.location = template.split("/")[3]
        self.timeout_seconds = timeout_seconds
        self.fail_closed = fail_closed
        self.max_chunk_chars = max_chunk_chars
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import modelarmor_v1

            self._client = modelarmor_v1.ModelArmorClient(
                client_options=ClientOptions(
                    api_endpoint=f"modelarmor.{self.location}.rep.googleapis.com"
                )
            )
        return self._client

    @classmethod
    def _matched_filters(cls, sanitization_result: Any) -> tuple[str, ...]:
        """Collect the names of filters that reported MATCH_FOUND."""
        matched: list[str] = []
        filter_results = getattr(sanitization_result, "filter_results", {}) or {}
        for key, result in dict(filter_results).items():
            for field_name in cls.FILTER_FIELDS:
                inner = getattr(result, field_name, None)
                if inner is None:
                    continue
                state = getattr(inner, "match_state", None)
                state_name = getattr(state, "name", str(state))
                if state_name == "MATCH_FOUND":
                    matched.append(str(key) or field_name)
                    break
        return tuple(sorted(set(matched)))

    @staticmethod
    def _policy_hit(matched: tuple[str, ...], block_on: frozenset[str] | None) -> bool:
        if block_on is None:
            return bool(matched)
        return any(name.startswith(prefix) for name in matched for prefix in block_on)

    def _chunks(self, text: str) -> Iterator[str]:
        for start in range(0, max(len(text), 1), self.max_chunk_chars):
            yield text[start : start + self.max_chunk_chars]

    def _sanitize(self, text: str, stage: ScreenStage, user_prompt: str | None) -> Any:
        from google.cloud import modelarmor_v1

        client = self._get_client()
        if stage is ScreenStage.RESPONSE:
            request = modelarmor_v1.SanitizeModelResponseRequest(
                name=self.template,
                model_response_data=modelarmor_v1.DataItem(text=text),
            )
            if user_prompt:
                request.user_prompt = user_prompt
            return client.sanitize_model_response(request=request, timeout=self.timeout_seconds)
        return client.sanitize_user_prompt(
            request=modelarmor_v1.SanitizeUserPromptRequest(
                name=self.template,
                user_prompt_data=modelarmor_v1.DataItem(text=text),
            ),
            timeout=self.timeout_seconds,
        )

    def screen(self, prompt: str) -> ModelArmorVerdict:
        """Screen an inbound user prompt (ingress stage)."""
        return self.screen_text(prompt, ScreenStage.PROMPT)

    def screen_text(
        self,
        text: str,
        stage: ScreenStage,
        *,
        user_prompt: str | None = None,
        block_on: frozenset[str] | None | Literal["policy"] = "policy",
    ) -> ModelArmorVerdict:
        """
        Screen `text` for the given stage. `block_on` defaults to the stage's
        entry in BLOCK_POLICY; pass an explicit frozenset or None to override.
        API failures degrade according to `fail_closed`.
        """
        policy: frozenset[str] | None = BLOCK_POLICY[stage] if isinstance(block_on, str) else block_on
        matched_all: list[str] = []
        overall_match = False
        chunk_count = 0
        for chunk in self._chunks(text):
            chunk_count += 1
            try:
                response = self._sanitize(chunk, stage, user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Model Armor screening unavailable.",
                    extra={
                        "event": "model_armor_degraded",
                        "stage": stage.value,
                        "error_type": type(exc).__name__,
                        "fail_closed": self.fail_closed,
                    },
                )
                return ModelArmorVerdict(
                    blocked=self.fail_closed,
                    stage=stage.value,
                    degraded=True,
                    detail=f"Model Armor unavailable ({type(exc).__name__})",
                    chunks=chunk_count,
                )
            result = response.sanitization_result
            overall = getattr(result.filter_match_state, "name", str(result.filter_match_state))
            matched = self._matched_filters(result)
            matched_all.extend(matched)
            if overall == "MATCH_FOUND":
                overall_match = True
                if self._policy_hit(matched, policy):
                    break

        matched_tuple = tuple(sorted(set(matched_all)))
        blocked = overall_match and self._policy_hit(matched_tuple, policy)
        logger.info(
            "Model Armor screening completed.",
            extra={
                "event": "model_armor_screen",
                "stage": stage.value,
                "blocked": blocked,
                "matched_filters": list(matched_tuple),
                "chunks": chunk_count,
            },
        )
        return ModelArmorVerdict(
            blocked=blocked,
            stage=stage.value,
            matched_filters=matched_tuple,
            chunks=chunk_count,
            detail=(
                f"Model Armor matched filters: {', '.join(matched_tuple) or 'MATCH_FOUND'}"
                if blocked
                else ""
            ),
        )
