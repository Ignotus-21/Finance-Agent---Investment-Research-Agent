"""
Pre-Execution Security Guardrails.
Intercepts adversarial jailbreak attempts, prompt injections, and scope violations
before dispatching queries to downstream LLM reasoning loops, screens the prompt
with Model Armor, then redacts PII through the configured masking backend (regex
or Cloud DLP). The same Model Armor client screens tool output (indirect prompt
injection) and outbound responses (egress).
"""

import logging
import re

from starlette.concurrency import run_in_threadpool

from src.config import Settings
from src.core.exceptions import (
    OutOfDomainQueryException,
    ResponseBlockedException,
    SecurityViolationException,
)
from src.core.interfaces import GuardrailInterface
from src.guardrails.dlp_masker import PIIMaskerProtocol, build_pii_masker
from src.guardrails.model_armor import ModelArmorScreen, ModelArmorVerdict, ScreenStage
from src.guardrails.scope_classifier import ScopeClassifier

logger = logging.getLogger(__name__)


class InputGuardrail(GuardrailInterface):
    """
    Pre-execution security classifier enforcing domain scope, PII redaction,
    and blocking adversarial prompt injections.

    Ingress layers, in order: length check → adversarial pattern interception →
    scope classification → Model Armor screening (optional) → PII masking.
    Also exposes Model Armor screening for tool output and outbound responses.
    """

    ADVERSARIAL_PATTERNS = [
        # Direct instruction overrides
        r"(?i)\bignore\s+(all\s+)?prior\s+instructions\b",
        r"(?i)\bdisregard\s+(all\s+)?previous\s+(rules|prompts|instructions)\b",
        r"(?i)\bsystem\s+prompt\s+override\b",
        # Persona adoption jailbreaks (DAN, unrestricted mode, grandmother exploit)
        r"(?i)\bact\s+as\s+(a\s+)?(dan|unrestricted|jailbroken|an\s+unfiltered)\b",
        r"(?i)\bact\s+as\s+my\s+grandmother\b",
        # Secret & credential harvesting
        r"(?i)\b(reveal|print|disclose|dump)\s+(all\s+)?(secret|internal|system|api|credentials|keys)\b",
        r"(?i)\bconnection\s+string\b",
        # Privilege escalation
        r"(?i)\[admin\s+override\]",
        r"(?i)\bmaintenance\s+mode\b",
        # SQL Injection attempts
        r"(?i);\s*drop\s+table\b",
        r"(?i);\s*select\s+\*\s+from\b",
        r"(?i)union\s+select\b",
        # Remote Code Execution (RCE) patterns
        r"(?i)\bimport\s+os\b",
        r"(?i)os\.system\(",
        r"(?i)subprocess\.(run|Popen)\(",
        r"(?i)rm\s+-rf\s+/",
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        masker: PIIMaskerProtocol | None = None,
        model_armor: ModelArmorScreen | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.masker: PIIMaskerProtocol = masker or build_pii_masker(
            backend=self.settings.dlp_backend,
            project_id=self.settings.gcp_project_id,
        )
        self.model_armor: ModelArmorScreen | None = model_armor
        if self.model_armor is None and self.settings.enable_model_armor:
            self.model_armor = ModelArmorScreen(
                template=self.settings.model_armor_template,
                timeout_seconds=self.settings.model_armor_timeout_seconds,
                fail_closed=self.settings.model_armor_fail_closed,
                max_chunk_chars=self.settings.model_armor_max_chunk_chars,
            )

    @property
    def screens_tool_output(self) -> bool:
        return self.model_armor is not None and self.settings.model_armor_screen_tool_output

    @property
    def screens_responses(self) -> bool:
        return self.model_armor is not None and self.settings.model_armor_screen_responses

    def validate_input(self, prompt: str, require_financial_anchor: bool = True) -> tuple[bool, str]:
        """
        Validates the incoming user prompt with the in-process classifiers.
        Returns: (is_valid, message)
        """
        if not prompt or not prompt.strip():
            return False, "Prompt cannot be empty."

        if len(prompt) > self.settings.max_prompt_chars:
            return (
                False,
                f"Prompt exceeds maximum allowed character length ({self.settings.max_prompt_chars}).",
            )

        # 1. Inspect for Adversarial Prompt Injection & Jailbreak patterns
        for pattern in self.ADVERSARIAL_PATTERNS:
            if re.search(pattern, prompt):
                return False, f"Adversarial security pattern detected matching signature: '{pattern}'"

        # 2. Inspect for Financial Domain Scope
        is_in_scope, scope_msg = ScopeClassifier.evaluate_scope(
            prompt, require_anchor=require_financial_anchor
        )
        if not is_in_scope:
            return False, scope_msg

        return True, "Passed security and scope inspection."

    def screen_with_model_armor(self, prompt: str) -> None:
        """Raise SecurityViolationException when Model Armor reports a filter match (ingress)."""
        if self.model_armor is None:
            return
        verdict = self.model_armor.screen(prompt)
        if verdict.blocked:
            raise SecurityViolationException(
                message=f"Model Armor blocked the request: {verdict.detail}",
                details={
                    "guardrail": "model_armor",
                    "stage": verdict.stage,
                    "matched_filters": list(verdict.matched_filters),
                    "degraded": verdict.degraded,
                },
            )

    def screen_tool_output(self, text: str, source: str) -> ModelArmorVerdict:
        """
        Screen content returned by a tool or sub-agent for indirect prompt injection.
        Returns the verdict; callers decide how to withhold the content.
        """
        if not self.screens_tool_output or self.model_armor is None or not text.strip():
            return ModelArmorVerdict(blocked=False, stage=ScreenStage.TOOL_OUTPUT.value, chunks=0)
        verdict = self.model_armor.screen_text(text, ScreenStage.TOOL_OUTPUT)
        if verdict.blocked:
            logger.warning(
                "Tool output withheld by Model Armor.",
                extra={
                    "event": "tool_output_withheld",
                    "source": source,
                    "matched_filters": list(verdict.matched_filters),
                    "degraded": verdict.degraded,
                },
            )
        return verdict

    def screen_response(self, text: str, user_prompt: str | None = None) -> None:
        """Raise ResponseBlockedException when outbound text fails egress screening."""
        if not self.screens_responses or self.model_armor is None or not text.strip():
            return
        verdict = self.model_armor.screen_text(text, ScreenStage.RESPONSE, user_prompt=user_prompt)
        if verdict.blocked:
            raise ResponseBlockedException(
                reason=verdict.detail, matched_filters=list(verdict.matched_filters)
            )

    async def screen_response_async(self, text: str, user_prompt: str | None = None) -> None:
        await run_in_threadpool(self.screen_response, text, user_prompt)

    def enforce(self, prompt: str, require_financial_anchor: bool = True) -> None:
        """Run the in-process checks and raise the matching domain exception on failure."""
        is_valid, msg = self.validate_input(prompt, require_financial_anchor)
        if not is_valid:
            if "Adversarial security" in msg or "signature" in msg:
                raise SecurityViolationException(message=msg)
            raise OutOfDomainQueryException(message=msg)

    def _mask(self, prompt: str) -> str:
        if not self.settings.enable_dlp_masking:
            return prompt
        sanitized, modified = self.masker.sanitize_text(prompt)
        logger.info(
            "Inbound prompt sanitised.",
            extra={
                "event": "pii_masking",
                "dlp_backend": self.masker.backend_name,
                "redaction_applied": modified,
            },
        )
        return sanitized

    def inspect_and_sanitize(self, prompt: str) -> str:
        """
        Runs validation, Model Armor screening and PII sanitization synchronously.
        Raises SecurityViolationException or OutOfDomainQueryException on violation.
        """
        self.enforce(prompt)
        self.screen_with_model_armor(prompt)
        return self._mask(prompt)

    async def inspect_and_sanitize_async(self, prompt: str) -> str:
        """
        Async variant for request handlers: in-process checks run inline; Model Armor
        and masking run on a worker thread so network round trips never block the loop.
        """
        self.enforce(prompt)
        await run_in_threadpool(self.screen_with_model_armor, prompt)
        return await run_in_threadpool(self._mask, prompt)
