"""
Cloud DLP (Data Loss Prevention) Sanitization Layer.
Redacts proprietary portfolio allocations, fund identifiers, and analyst PII
prior to entering the LLM reasoning context or the audit logs.
"""

import re


class CloudDLPMasker:
    """Sanitizes user input by masking PII and proprietary institutional portfolio codes."""

    # Regex patterns for proprietary portfolio references and analyst PII
    PATTERNS = [
        # Email Addresses
        (r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED_EMAIL]"),
        # Phone Numbers
        (r"\b(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b", "[REDACTED_PHONE]"),
        # Institutional Fund Codes (e.g. FUND-9821, ACCT-00213, PORTFOLIO-X)
        (r"\b(?:FUND|ACCT|PORTFOLIO|DESK)-[A-Z0-9]{4,12}\b", "[REDACTED_FUND_ID]"),
        # Proprietary share quantities in internal portfolios (e.g. "We hold 450,000 shares")
        (r"(?i)\b(?:we\s+hold|our\s+position\s+is|holding|long\s+position\s+of)\s+(\d+(?:,\d+)*(?:\.\d+)?)\s+(?:shares|units)\b", "holding [REDACTED_POSITION_SIZE] shares"),
    ]

    @classmethod
    def sanitize_text(cls, text: str) -> tuple[str, bool]:
        """
        Scrub sensitive PII and proprietary fund metadata.
        Returns: (sanitized_text, was_modified)
        """
        sanitized = text
        was_modified = False

        for pattern, replacement in cls.PATTERNS:
            new_text, count = re.subn(pattern, replacement, sanitized)
            if count > 0:
                was_modified = True
                sanitized = new_text

        return sanitized, was_modified
