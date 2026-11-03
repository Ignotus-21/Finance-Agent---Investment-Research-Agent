"""
Cloud DLP de-identification backend for inbound prompt sanitisation.
Redacts analyst identifiers and proprietary portfolio metadata through the
Google Cloud Data Loss Prevention API, with the in-process regex masker applied
afterwards as a defence-in-depth second pass.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from src.guardrails.pii_masker import PIIMasker

logger = logging.getLogger(__name__)


class PIIMaskerProtocol(Protocol):
    """Contract shared by the regex and Cloud DLP maskers."""

    backend_name: str

    def sanitize_text(self, text: str) -> tuple[str, bool]: ...


class RegexPIIMasker:
    """In-process regex masker (no network dependency)."""

    backend_name = "regex"

    def sanitize_text(self, text: str) -> tuple[str, bool]:
        return PIIMasker.sanitize_text(text)


class CloudDLPMasker:
    """
    Redacts PII and proprietary identifiers with the Cloud DLP
    `deidentifyContent` API (replace-with-infoType transformation).

    Built-in infoTypes cover analyst contact and payment identifiers; custom
    infoTypes cover institutional fund codes and internal position sizes.
    PERSON_NAME is intentionally excluded so executive names in legitimate
    research questions (e.g. CFO quotes) are preserved.
    """

    backend_name = "cloud_dlp"

    BUILTIN_INFO_TYPES: tuple[str, ...] = (
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SOCIAL_SECURITY_NUMBER",
        "CREDIT_CARD_NUMBER",
        "IBAN_CODE",
        "IP_ADDRESS",
    )
    CUSTOM_INFO_TYPES: tuple[tuple[str, str], ...] = (
        ("INSTITUTIONAL_FUND_ID", r"\b(?:FUND|ACCT|PORTFOLIO|DESK)-[A-Z0-9]{4,12}\b"),
        (
            "INTERNAL_POSITION_SIZE",
            r"(?i)\b(?:we\s+hold|our\s+position\s+is|holding|long\s+position\s+of)\s+\d+(?:,\d+)*(?:\.\d+)?\s+(?:shares|units)\b",
        ),
    )

    def __init__(
        self,
        project_id: str,
        location: str = "global",
        client: Any | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.timeout_seconds = timeout_seconds
        self._client = client

    @property
    def parent(self) -> str:
        return f"projects/{self.project_id}/locations/{self.location}"

    def _get_client(self) -> Any:
        if self._client is None:
            import google.cloud.dlp_v2 as dlp_v2

            self._client = dlp_v2.DlpServiceClient()
        return self._client

    def build_request(self, text: str) -> dict[str, Any]:
        """Construct the deidentifyContent request body for the given text."""
        return {
            "parent": self.parent,
            "inspect_config": {
                "info_types": [{"name": name} for name in self.BUILTIN_INFO_TYPES],
                "custom_info_types": [
                    {"info_type": {"name": name}, "regex": {"pattern": pattern}}
                    for name, pattern in self.CUSTOM_INFO_TYPES
                ],
                "min_likelihood": "POSSIBLE",
                "include_quote": False,
            },
            "deidentify_config": {
                "info_type_transformations": {
                    "transformations": [
                        {"primitive_transformation": {"replace_with_info_type_config": {}}}
                    ]
                }
            },
            "item": {"value": text},
        }

    def sanitize_text(self, text: str) -> tuple[str, bool]:
        """
        De-identify with Cloud DLP, then apply the regex pass. If the DLP call
        fails, fall back to the regex masker alone and record the degradation.
        """
        dlp_text = text
        dlp_modified = False
        try:
            response = self._get_client().deidentify_content(
                request=self.build_request(text), timeout=self.timeout_seconds
            )
            dlp_text = response.item.value
            dlp_modified = dlp_text != text
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Cloud DLP de-identification unavailable; regex masker applied alone.",
                extra={"dlp_backend": self.backend_name, "error_type": type(exc).__name__},
            )

        regex_text, regex_modified = PIIMasker.sanitize_text(dlp_text)
        return regex_text, dlp_modified or regex_modified


def build_pii_masker(
    backend: str,
    project_id: str,
    client: Any | None = None,
) -> PIIMaskerProtocol:
    """Return the masker implementation selected by `DLP_BACKEND`."""
    if backend == "cloud_dlp":
        return CloudDLPMasker(project_id=project_id, client=client)
    return RegexPIIMasker()
