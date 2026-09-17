"""
Abstract Base Classes and Interfaces defining contracts across the application.
Enables dependency injection and isolated unit test mocking.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Abstract base class for all autonomous agents in the multi-agent system."""

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Name of the specialized sub-agent or coordinator."""
        pass

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute agent reasoning or data processing loop."""
        pass


class BaseTool(ABC):
    """Abstract base class for all deterministic and external tools.

    Intentionally declares only LLM-facing metadata. There is no abstract
    ``execute(**kwargs)``: no caller ever dispatches a tool polymorphically, and every
    tool exposes a strongly-typed method instead (``fetch_filing_section``,
    ``get_transcript``, ``query_market_context``). An untyped ``**kwargs`` escape hatch
    would only erase those signatures.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier of the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Detailed description consumable by LLMs."""
        pass


# The three interfaces below each have exactly one production implementation today.
# They are retained deliberately: they are the documented swap points from ADR-002
# (MCP vs REST filing backends) and they are what unit tests substitute fakes for.
class FilingRetrievalInterface(ABC):
    """Abstract interface for SEC filing retrieval backends (MCP, REST, cached fallback)."""

    @abstractmethod
    async def fetch_filing_section(
        self, ticker: str, form: str, fiscal_year: int, section: str
    ) -> dict[str, Any]:
        """Retrieve and parse a specific SEC filing section."""
        pass


class MarketDataInterface(ABC):
    """Abstract interface for macroeconomic and market news search grounding."""

    @abstractmethod
    async def query_market_context(
        self, ticker: str, focus_areas: list[str]
    ) -> list[dict[str, Any]]:
        """Retrieve live macroeconomic context and grounded news snippets."""
        pass


class GuardrailInterface(ABC):
    """Abstract interface for pre-execution security and safety classifiers."""

    @abstractmethod
    def validate_input(self, prompt: str) -> tuple[bool, str]:
        """
        Validate incoming user prompt.
        Returns (is_valid, reason_or_error_message).
        """
        pass
