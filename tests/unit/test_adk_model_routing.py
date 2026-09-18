"""Tests for ADK model routing and context caching.

Both features were claimed by the documentation and absent from the code.

``extraction_model`` was declared in ``src/config.py``, set on the Cloud Run
revision by Terraform as ``EXTRACTION_MODEL``, and referenced nowhere - the ADK
agent was a single flat agent hard-coded to ``gemini-2.5-pro``.

Context caching was a module in ``src/cache/`` that kept an in-process dict,
estimated tokens as ``max(35000, len // 4)``, and returned a "cost saved" figure
computed from a hardcoded price delta against a ``cache_id`` naming a Vertex
resource that had never been created. It called no Google API of any kind.
"""

import pytest
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import McpToolset

from src.agents.adk_agent import (
    create_filing_extraction_agent,
    create_financial_adk_agent,
    create_financial_adk_app,
)
from src.config import Settings

# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------


def test_the_two_agents_run_on_different_models() -> None:
    """The whole point. One model for both is the state this PR fixes."""
    settings = Settings()
    coordinator = create_financial_adk_agent()
    extractor = coordinator.tools[0].agent

    assert coordinator.model.model == settings.coordinator_model
    assert extractor.model.model == settings.extraction_model
    assert coordinator.model.model != extractor.model.model


def test_models_come_from_settings_not_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    """`COORDINATOR_MODEL` and `EXTRACTION_MODEL` on the revision must reach the agents.

    Terraform has been setting both env vars since #13. Until now the extraction
    one changed nothing at all, and the coordinator one changed nothing either -
    the model name was a default argument in the factory.
    """
    monkeypatch.setenv("COORDINATOR_MODEL", "gemini-3-pro-preview")
    monkeypatch.setenv("EXTRACTION_MODEL", "gemini-2.0-flash")

    coordinator = create_financial_adk_agent()

    assert coordinator.model.model == "gemini-3-pro-preview"
    assert coordinator.tools[0].agent.model.model == "gemini-2.0-flash"


def test_explicit_arguments_still_win() -> None:
    agent = create_financial_adk_agent(
        model_name="gemini-2.5-pro", extraction_model_name="gemini-2.5-flash-lite"
    )
    assert agent.model.model == "gemini-2.5-pro"
    assert agent.tools[0].agent.model.model == "gemini-2.5-flash-lite"


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


def test_retrieval_tools_live_on_the_specialist_and_not_on_both() -> None:
    """Two paths to the same data drift apart; this asserts there is one."""
    coordinator = create_financial_adk_agent()
    extractor = coordinator.tools[0].agent

    assert sum(isinstance(t, McpToolset) for t in extractor.tools) == 1
    assert not any(isinstance(t, McpToolset) for t in coordinator.tools)

    extractor_tool_names = {getattr(t, "__name__", type(t).__name__) for t in extractor.tools}
    assert "get_earnings_call_transcript" in extractor_tool_names


def test_the_calculator_stays_with_the_coordinator() -> None:
    """Arithmetic must not be delegated to the model that reads the filing.

    ``compute_financial_ratios`` is deterministic Python. Keeping it beside the
    synthesis step is what makes "never guess a margin" enforceable in one
    place rather than asserted in two system prompts.
    """
    coordinator = create_financial_adk_agent()
    names = {getattr(t, "__name__", type(t).__name__) for t in coordinator.tools}

    assert "compute_financial_ratios" in names
    assert "query_macro_market_news" in names

    extractor_names = {
        getattr(t, "__name__", type(t).__name__) for t in coordinator.tools[0].agent.tools
    }
    assert "compute_financial_ratios" not in extractor_names


def test_delegation_is_a_tool_call_not_a_transfer() -> None:
    """`sub_agents` would hand the conversation to Flash and never get it back.

    The coordinator has to regain control to write the brief, so the specialist
    is an ``AgentTool``. If this ever becomes a transfer, the synthesis step
    silently starts running on the extraction model.
    """
    coordinator = create_financial_adk_agent()

    assert isinstance(coordinator.tools[0], AgentTool)
    assert not coordinator.sub_agents


def test_the_specialist_is_described_for_the_coordinator_to_read() -> None:
    """An AgentTool with no description is a tool the planner cannot choose."""
    assert create_filing_extraction_agent().description.strip()


# ---------------------------------------------------------------------------
# Context caching
# ---------------------------------------------------------------------------


def test_app_enables_adk_context_caching() -> None:
    config = create_financial_adk_app().context_cache_config

    assert isinstance(config, ContextCacheConfig)
    assert config.ttl_seconds == Settings().context_cache_ttl_minutes * 60


def test_min_tokens_states_geminis_real_floor() -> None:
    """ADK defaults this to 0, which reads as "cache everything" and is not true.

    Gemini will not cache a prefix below 2048 tokens for the 2.5 family no
    matter what is configured. Writing it down is the difference between a
    reader concluding the cache is broken and concluding the request was small.
    """
    assert create_financial_adk_app().context_cache_config.min_tokens == 2048


def test_context_cache_config_is_overridable() -> None:
    override = ContextCacheConfig(ttl_seconds=60, min_tokens=4096)
    assert create_financial_adk_app(context_cache_config=override).context_cache_config is override


def test_the_simulated_cache_module_is_gone() -> None:
    """`src/cache/context_caching.py` reported savings it had not made."""
    with pytest.raises(ModuleNotFoundError):
        __import__("src.cache.context_caching")
