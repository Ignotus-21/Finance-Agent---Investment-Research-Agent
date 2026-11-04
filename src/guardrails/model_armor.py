"""
Model Armor prompt screening.
Screens inbound prompts against a Google Cloud Model Armor template (prompt
injection and jailbreak detection, responsible-AI categories, malicious URIs,
sensitive data) as an additional pre-execution guardrail layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelArmorVerdict:
    """Outcome of a Model Armor screening call."""

    blocked: bool
    matched_filters: tuple[str, ...] = ()
    degraded: bool = False
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


class ModelArmorScreen:
    """
    Calls `SanitizeUserPrompt` on a Model Armor template and reduces the
    sanitization result to a block / allow verdict.

    `template` is the full resource name
    `projects/<project>/locations/<location>/templates/<template_id>`.
    Model Armor is a regional API; the client targets
    `modelarmor.<location>.rep.googleapis.com`.
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
    ) -> None:
        if not template or template.count("/") < 5:
            raise ValueError(
                "MODEL_ARMOR_TEMPLATE must be a full resource name "
                "'projects/<project>/locations/<location>/templates/<id>'."
            )
        self.template = template
        self.location = template.split("/")[3]
        self.timeout_seconds = timeout_seconds
        self.fail_closed = fail_closed
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

    def screen(self, prompt: str) -> ModelArmorVerdict:
        """Screen a prompt; API failures degrade according to `fail_closed`."""
        try:
            from google.cloud import modelarmor_v1

            response = self._get_client().sanitize_user_prompt(
                request=modelarmor_v1.SanitizeUserPromptRequest(
                    name=self.template,
                    user_prompt_data=modelarmor_v1.DataItem(text=prompt),
                ),
                timeout=self.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Model Armor screening unavailable.",
                extra={
                    "event": "model_armor_degraded",
                    "error_type": type(exc).__name__,
                    "fail_closed": self.fail_closed,
                },
            )
            return ModelArmorVerdict(
                blocked=self.fail_closed,
                degraded=True,
                detail=f"Model Armor unavailable ({type(exc).__name__})",
            )

        result = response.sanitization_result
        overall = getattr(result.filter_match_state, "name", str(result.filter_match_state))
        matched = self._matched_filters(result)
        blocked = overall == "MATCH_FOUND"
        logger.info(
            "Model Armor screening completed.",
            extra={
                "event": "model_armor_screen",
                "blocked": blocked,
                "matched_filters": list(matched),
            },
        )
        return ModelArmorVerdict(
            blocked=blocked,
            matched_filters=matched,
            detail=f"Model Armor matched filters: {', '.join(matched) or overall}" if blocked else "",
        )
