"""
Pre-Execution Security Guardrails.
Intercepts adversarial jailbreak attempts, prompt injections, and scope violations
before dispatching queries to downstream LLM reasoning loops, then redacts PII
through the configured masking backend (regex or Cloud DLP).
"""

import logging
import re

from starlette.concurrency import run_in_threadpool

from src.config import Settings
from src.core.exceptions import OutOfDomainQueryException, SecurityViolationException
from src.core.interfaces import GuardrailInterface
from src.guardrails.dlp_masker import PIIMaskerProtocol, build_pii_masker
from src.guardrails.scope_classifier import ScopeClassifier

logger = logging.getLogger(__name__)


class InputGuardrail(GuardrailInterface):
    """
    Pre-execution security classifier enforcing domain scope, PII redaction,
    and blocking adversarial prompt injections.
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
    ) -> None:
        self.settings = settings or Settings()
        self.masker: PIIMaskerProtocol = masker or build_pii_masker(
            backend=self.settings.dlp_backend,
            project_id=self.settings.gcp_project_id,
        )

    def validate_input(self, prompt: str) -> tuple[bool, str]:
        """
        Validates the incoming user prompt.
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
        is_in_scope, scope_msg = ScopeClassifier.evaluate_scope(prompt)
        if not is_in_scope:
            return False, scope_msg

        return True, "Passed security and scope inspection."

    def _enforce(self, prompt: str) -> None:
        is_valid, msg = self.validate_input(prompt)
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
        Runs validation and PII sanitization synchronously.
        Raises SecurityViolationException or OutOfDomainQueryException on violation.
        """
        self._enforce(prompt)
        return self._mask(prompt)

    async def inspect_and_sanitize_async(self, prompt: str) -> str:
        """
        Async variant for request handlers: validation runs inline, masking runs on a
        worker thread so a Cloud DLP round trip never blocks the event loop.
        """
        self._enforce(prompt)
        return await run_in_threadpool(self._mask, prompt)
