"""Hierarchical multi-agent layer: Root Coordinator and domain specialist sub-agents.

Note: ``root_agent`` and ``app`` are deliberately NOT re-exported here. They live in
``src.agents.agent`` because constructing them instantiates a Gemini-backed ADK Agent;
re-exporting would make that a side effect of importing any sibling module.
Import them explicitly: ``from src.agents.agent import root_agent, app``.
"""

from src.agents.macro_agent import MacroSubAgent
from src.agents.root_coordinator import RootCoordinatorAgent
from src.agents.sec_agent import SECSubAgent
from src.agents.transcript_agent import TranscriptSubAgent

__all__ = [
    "MacroSubAgent",
    "RootCoordinatorAgent",
    "SECSubAgent",
    "TranscriptSubAgent",
]
