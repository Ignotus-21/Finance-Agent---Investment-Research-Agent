"""
ADK guardrail callbacks.
Applies the same pre-execution guardrail stack used by the REST API (adversarial
pattern interception, topic blocklist, Model Armor screening) to the ADK
coordinator through `before_model_callback`, so `adk web`, `adk run` and the
`/adk` surface cannot bypass the security layer.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.genai import types
from starlette.concurrency import run_in_threadpool

from src.core.exceptions import FinancialAgentException
from src.guardrails.input_guardrail import InputGuardrail

logger = logging.getLogger(__name__)

_SCREENED_STATE_KEY = "temp:ira_guardrail_screened_hash"

BeforeModelGuardrail = Callable[[CallbackContext, LlmRequest], Awaitable[LlmResponse | None]]


def extract_latest_user_text(llm_request: LlmRequest) -> str | None:
    """
    Return the text of the most recent user turn, or None when the pending model
    call is a tool-result continuation (function responses) rather than new input.
    """
    contents = llm_request.contents or []
    if not contents:
        return None
    last = contents[-1]
    if last.role != "user" or not last.parts:
        return None
    if any(part.function_response is not None for part in last.parts):
        return None
    text = "\n".join(part.text for part in last.parts if part.text)
    return text.strip() or None


def _refusal(message: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=message)]),
        custom_metadata={"guardrail_blocked": True},
    )


def build_before_model_guardrail(
    guardrail: InputGuardrail | None = None,
) -> BeforeModelGuardrail:
    """
    Build an async `before_model_callback` that screens each new user turn.

    The financial-anchor requirement is relaxed for the conversational surface
    (follow-ups such as "and the prior year?" carry no anchor term); adversarial
    patterns, blocked topics and Model Armor verdicts are enforced unchanged.
    Each turn is screened once per invocation (tracked in temp session state).
    """
    _guardrail = guardrail

    def _get_guardrail() -> InputGuardrail:
        nonlocal _guardrail
        if _guardrail is None:
            _guardrail = InputGuardrail()
        return _guardrail

    async def before_model_guardrail(
        callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        prompt = extract_latest_user_text(llm_request)
        if prompt is None:
            return None

        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if callback_context.state.get(_SCREENED_STATE_KEY) == digest:
            return None

        active = _get_guardrail()
        try:
            active.enforce(prompt, require_financial_anchor=False)
            await run_in_threadpool(active.screen_with_model_armor, prompt)
        except FinancialAgentException as exc:
            logger.warning(
                "ADK guardrail blocked a prompt.",
                extra={
                    "event": "adk_guardrail_block",
                    "error_code": exc.error_code,
                    "agent": callback_context.agent_name,
                    "details": exc.details,
                },
            )
            return _refusal(
                "This request was blocked by the IRA security guardrails "
                f"({exc.error_code}). Rephrase it as a corporate fundamental "
                "research question about a publicly listed company."
            )

        callback_context.state[_SCREENED_STATE_KEY] = digest
        return None

    return before_model_guardrail
