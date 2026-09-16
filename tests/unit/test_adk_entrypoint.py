"""
Unit test for ADK CLI entry point (src/agents/agent.py).
Ensures compatibility with ADK loader and CLI discovery.
"""

from google.adk.cli.utils.agent_loader import AgentLoader, is_single_agent_directory

from src.agents.agent import app, root_agent


def test_adk_agent_entrypoint():
    """Verify that root_agent and app are properly exposed."""
    assert root_agent is not None
    assert root_agent.name == "finance_investment_research_agent"
    assert app is not None
    assert app.name == "finance_research_app"


def test_adk_agent_loader_discovery():
    """Verify that ADK's AgentLoader discovers src/agents cleanly."""
    path = "src/agents"
    assert is_single_agent_directory(path) is True

    loader = AgentLoader(path)
    assert loader.is_single_agent is True
    assert loader.single_agent_name == "agents"

    loaded = loader.load_agent("agents")
    assert loaded is not None
