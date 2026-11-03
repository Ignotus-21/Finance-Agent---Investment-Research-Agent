"""Tests for externalized generation settings and live news grounding on the ADK topology."""

import pytest
from google.adk.planners import BuiltInPlanner
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool

from src.agents.adk_agent import (
    build_generate_content_config,
    create_financial_adk_agent,
    create_macro_news_agent,
)
from src.config import Settings


def test_generation_config_reflects_settings_yaml_defaults() -> None:
    settings = Settings()
    cfg = build_generate_content_config(settings)

    assert cfg.temperature == settings.temperature == 0.1
    assert cfg.top_p == settings.top_p == 0.95
    assert cfg.max_output_tokens == settings.max_output_tokens == 8192
    assert {s.threshold.name for s in cfg.safety_settings} == {"BLOCK_MEDIUM_AND_ABOVE"}
    assert len(cfg.safety_settings) == 4


def test_generation_config_is_overridable_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPERATURE", "0.4")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("SAFETY_HARM_BLOCK_THRESHOLD", "BLOCK_ONLY_HIGH")

    cfg = build_generate_content_config(Settings())

    assert cfg.temperature == 0.4
    assert cfg.max_output_tokens == 2048
    assert all(s.threshold.name == "BLOCK_ONLY_HIGH" for s in cfg.safety_settings)


def test_invalid_safety_threshold_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_HARM_BLOCK_THRESHOLD", "BLOCK_EVERYTHING")
    with pytest.raises(ValueError, match="SAFETY_HARM_BLOCK_THRESHOLD"):
        Settings()


def test_both_agents_carry_the_generation_config() -> None:
    coordinator = create_financial_adk_agent()
    extractor = coordinator.tools[0].agent

    assert coordinator.generate_content_config.temperature == 0.1
    assert extractor.generate_content_config.max_output_tokens == 8192


def test_coordinator_thinking_budget_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COORDINATOR_THINKING_BUDGET", "512")
    coordinator = create_financial_adk_agent()

    assert isinstance(coordinator.planner, BuiltInPlanner)
    assert coordinator.planner.thinking_config.thinking_budget == 512


def test_live_news_grounding_is_off_by_default_for_hermetic_runs() -> None:
    coordinator = create_financial_adk_agent()
    names = [getattr(t, "agent", None) and t.agent.name for t in coordinator.tools]
    assert "macro_news_specialist" not in names


def test_live_news_grounding_adds_a_google_search_specialist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_LIVE_NEWS_GROUNDING", "true")
    coordinator = create_financial_adk_agent()

    specialists = [t for t in coordinator.tools if isinstance(t, AgentTool)]
    assert [t.agent.name for t in specialists] == [
        "filing_extraction_specialist",
        "macro_news_specialist",
    ]
    macro = specialists[1].agent
    assert macro.tools == [google_search]
    assert "macro_news_specialist" in coordinator.instruction


def test_macro_news_specialist_only_holds_the_builtin_search_tool() -> None:
    agent = create_macro_news_agent()
    assert agent.tools == [google_search]
    assert agent.description.strip()
