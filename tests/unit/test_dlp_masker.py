"""Tests for the configurable PII masking backends (regex and Cloud DLP)."""

from types import SimpleNamespace

import pytest

from src.config import Settings
from src.guardrails.dlp_masker import CloudDLPMasker, RegexPIIMasker, build_pii_masker
from src.guardrails.input_guardrail import InputGuardrail

PROMPT = (
    "Analyze AAPL FY2024 margins for analyst jane.doe@fund.example (+1 415-555-0199); "
    "we hold 450,000 shares in FUND-A1B2C3."
)


class _FakeDlpClient:
    """Minimal stand-in for google.cloud.dlp_v2.DlpServiceClient."""

    def __init__(self, response_text: str | None = None, error: Exception | None = None) -> None:
        self.response_text = response_text
        self.error = error
        self.requests: list[dict] = []

    def deidentify_content(self, request: dict, timeout: float) -> SimpleNamespace:
        self.requests.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(item=SimpleNamespace(value=self.response_text))


def test_factory_selects_backend_from_settings() -> None:
    assert isinstance(build_pii_masker("regex", "proj"), RegexPIIMasker)
    assert isinstance(build_pii_masker("cloud_dlp", "proj"), CloudDLPMasker)


def test_settings_reject_unknown_dlp_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DLP_BACKEND", "magic")
    with pytest.raises(ValueError, match="DLP_BACKEND"):
        Settings()


def test_cloud_dlp_request_targets_project_with_builtin_and_custom_infotypes() -> None:
    masker = CloudDLPMasker(project_id="adis-workshop", client=_FakeDlpClient(PROMPT))
    request = masker.build_request(PROMPT)

    assert request["parent"] == "projects/adis-workshop/locations/global"
    builtin = {it["name"] for it in request["inspect_config"]["info_types"]}
    custom = {it["info_type"]["name"] for it in request["inspect_config"]["custom_info_types"]}
    assert {"EMAIL_ADDRESS", "PHONE_NUMBER"} <= builtin
    assert "PERSON_NAME" not in builtin
    assert {"INSTITUTIONAL_FUND_ID", "INTERNAL_POSITION_SIZE"} <= custom
    assert request["item"]["value"] == PROMPT


def test_cloud_dlp_output_is_used_and_regex_second_pass_still_applies() -> None:
    dlp_output = (
        "Analyze AAPL FY2024 margins for analyst [EMAIL_ADDRESS] ([PHONE_NUMBER]); "
        "we hold 450,000 shares in FUND-A1B2C3."
    )
    client = _FakeDlpClient(dlp_output)
    masker = CloudDLPMasker(project_id="adis-workshop", client=client)

    sanitized, modified = masker.sanitize_text(PROMPT)

    assert modified is True
    assert "[EMAIL_ADDRESS]" in sanitized and "[PHONE_NUMBER]" in sanitized
    assert "FUND-A1B2C3" not in sanitized and "450,000" not in sanitized
    assert len(client.requests) == 1


def test_cloud_dlp_failure_falls_back_to_regex_without_raising() -> None:
    masker = CloudDLPMasker(
        project_id="adis-workshop", client=_FakeDlpClient(error=RuntimeError("DLP unavailable"))
    )

    sanitized, modified = masker.sanitize_text(PROMPT)

    assert modified is True
    assert "jane.doe@fund.example" not in sanitized
    assert "[REDACTED_EMAIL]" in sanitized and "[REDACTED_FUND_ID]" in sanitized


def test_guardrail_uses_injected_masker_and_respects_prompt_limit() -> None:
    settings = Settings(max_prompt_chars=120)
    guard = InputGuardrail(
        settings=settings,
        masker=CloudDLPMasker(project_id="adis-workshop", client=_FakeDlpClient(PROMPT)),
    )

    sanitized = guard.inspect_and_sanitize(PROMPT)
    assert "[REDACTED_EMAIL]" in sanitized

    ok, message = guard.validate_input("revenue " * 40)
    assert ok is False and "120" in message


@pytest.mark.asyncio
async def test_async_guardrail_entrypoint_masks_off_the_event_loop() -> None:
    guard = InputGuardrail(settings=Settings(), masker=RegexPIIMasker())
    sanitized = await guard.inspect_and_sanitize_async(PROMPT)
    assert "[REDACTED_EMAIL]" in sanitized and "[REDACTED_POSITION_SIZE]" in sanitized
