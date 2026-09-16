"""Google ADK agent entry point for adk run and adk web CLI commands."""

from .adk_agent import create_financial_adk_agent, create_financial_adk_app

root_agent = create_financial_adk_agent()
app = create_financial_adk_app(root_agent)
