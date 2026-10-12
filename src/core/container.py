"""
Application Dependency Injection Container.
Wires tools, sub-agents, calculators, caching managers, and coordinators.
Allows complete dependency substitution for testing.
"""


from src.agents.macro_agent import MacroSubAgent
from src.agents.root_coordinator import RootCoordinatorAgent
from src.agents.sec_agent import SECSubAgent
from src.agents.transcript_agent import TranscriptSubAgent
from src.config import Settings
from src.engine.synthesis_engine import SynthesisEngine
from src.guardrails.input_guardrail import InputGuardrail
from src.tools.financial_calculator import FinancialCalculator
from src.tools.macro_context import MacroContextClient
from src.tools.sec_edgar_mcp import SECFilingClient
from src.tools.transcript_parser import TranscriptClient


class ApplicationContainer:
    """Central Dependency Injection Container assembling all components."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

        # Deterministic Tools & Adapters
        self.calculator = FinancialCalculator()
        self.sec_client = SECFilingClient(settings=self.settings)
        self.transcript_client = TranscriptClient(settings=self.settings)
        self.search_client = MacroContextClient(settings=self.settings)

        # Pre-execution Security Guardrails
        self.guardrail = InputGuardrail(settings=self.settings)

        # Specialized Sub-Agents
        self.sec_agent = SECSubAgent(client=self.sec_client, settings=self.settings)
        self.transcript_agent = TranscriptSubAgent(client=self.transcript_client, settings=self.settings)
        self.macro_agent = MacroSubAgent(client=self.search_client, settings=self.settings)

        # Synthesis Engine
        self.synthesis_engine = SynthesisEngine(calculator=self.calculator, settings=self.settings)

        # Root Coordinator Orchestrator
        self.root_coordinator = RootCoordinatorAgent(
            sec_agent=self.sec_agent,
            transcript_agent=self.transcript_agent,
            macro_agent=self.macro_agent,
            calculator=self.calculator,
            synthesis_engine=self.synthesis_engine,
            settings=self.settings
        )


container = ApplicationContainer()
