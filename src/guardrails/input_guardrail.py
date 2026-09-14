"""
Pre-Execution Security Guardrails.
Intercepts adversarial jailbreak attempts, prompt injections, and scope violations
before dispatching queries to downstream LLM reasoning loops.
"""

import re
from typing import Tuple, Dict, Any, Optional
from src.core.interfaces import GuardrailInterface
from src.core.exceptions import SecurityViolationException, OutOfDomainQueryException
from src.guardrails.dlp_masker import CloudDLPMasker
from src.guardrails.scope_classifier import ScopeClassifier
from src.config import Settings


class InputGuardrail(GuardrailInterface):
    """
    Pre-execution security classifier enforcing domain scope, DLP redaction,
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

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()

    def validate_input(self, prompt: str) -> Tuple[bool, str]:
        """
        Validates the incoming user prompt.
        Returns: (is_valid, message)
        """
        if not prompt or not prompt.strip():
            return False, "Prompt cannot be empty."

        if len(prompt) > 8000:
            return False, "Prompt exceeds maximum allowed character length (8000)."

        # 1. Inspect for Adversarial Prompt Injection & Jailbreak patterns
        for pattern in self.ADVERSARIAL_PATTERNS:
            if re.search(pattern, prompt):
                return False, f"Adversarial security pattern detected matching signature: '{pattern}'"

        # 2. Inspect for Financial Domain Scope
        is_in_scope, scope_msg = ScopeClassifier.evaluate_scope(prompt)
        if not is_in_scope:
            return False, scope_msg

        return True, "Passed security and scope inspection."

    def inspect_and_sanitize(self, prompt: str) -> str:
        """
        Runs validation and DLP sanitization.
        Raises SecurityViolationException or OutOfDomainQueryException on violation.
        """
        is_valid, msg = self.validate_input(prompt)
        if not is_valid:
            if "Adversarial security" in msg or "signature" in msg:
                raise SecurityViolationException(message=msg)
            else:
                raise OutOfDomainQueryException(message=msg)

        # Apply Cloud DLP masking
        sanitized_prompt, _ = CloudDLPMasker.sanitize_text(prompt)
        return sanitized_prompt
