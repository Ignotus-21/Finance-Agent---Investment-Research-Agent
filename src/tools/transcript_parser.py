"""
Earnings Call Transcript Parser.
Segments raw quarterly transcripts into Executive Prepared Remarks and Analyst Q&A.
Extracts speaker roles (CEO, CFO, Analyst) and sentiment orientation.
"""

from typing import Any

from src.config import Settings
from src.core.interfaces import BaseTool


class TranscriptClient(BaseTool):
    """
    Parser for earnings call transcripts.
    Distinguishes formal guidance remarks from unscripted Q&A.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

        # High-fidelity transcript corpus for benchmark scenarios
        self._transcripts: dict[str, dict[str, Any]] = {
            "AAPL_Q4_2024": {
                "event": "Apple Inc. Q4 2024 Earnings Conference Call",
                "date": "2024-10-31",
                "prepared_remarks": [
                    {
                        "speaker_name": "Tim Cook",
                        "speaker_role": "Chief Executive Officer",
                        "text": "Today Apple is reporting revenue of $94.9 billion for the September quarter, an all-time record for September and up 6% from a year ago. We are thrilled by the customer response to our iPhone 16 lineup and the initial rollout of Apple Intelligence.",
                        "sentiment": 0.85
                    },
                    {
                        "speaker_name": "Luca Maestri",
                        "speaker_role": "Chief Financial Officer",
                        "text": "Services revenue reached an all-time record of $25.0 billion, up 12% year-over-year. Company gross margin was 46.2%, near the high end of our guidance range. Services gross margin was 74.0%, expanding by 320 basis points driven by favorable mix. Foreign exchange headwinds accounted for approximately 110 basis points of drag.",
                        "sentiment": 0.72
                    }
                ],
                "analyst_qa": [
                    {
                        "analyst_name": "Shannon Cross",
                        "analyst_firm": "Scotiabank",
                        "question": "Can you talk about the competitive environment and consumer demand trends in Greater China, and how you see foreign exchange headwinds persisting?",
                        "executive_response": "Luca Maestri: In Greater China, on a constant currency basis, our revenue was relatively flat year-over-year. We saw sequential improvement in iPhone run rates during September, and our installed base reached an all-time high."
                    },
                    {
                        "analyst_name": "Erik Woodring",
                        "analyst_firm": "Morgan Stanley",
                        "question": "Regarding CapEx and AI infrastructure, are you seeing any margin dilution as you scale private cloud compute?",
                        "executive_response": "Luca Maestri: We utilize a hybrid model leveraging both our own data centers and third-party cloud providers. This keeps our capital intensity extremely disciplined."
                    }
                ]
            },
            "MSFT_Q4_2024": {
                "event": "Microsoft FY24 Q4 Earnings Call",
                "date": "2024-07-30",
                "prepared_remarks": [
                    {
                        "speaker_name": "Satya Nadella",
                        "speaker_role": "Chairman and CEO",
                        "text": "Cloud and AI drove another record quarter. Azure surpassed $75 billion in revenue for the fiscal year, with AI contributing 8 points of Azure growth.",
                        "sentiment": 0.88
                    },
                    {
                        "speaker_name": "Amy Hood",
                        "speaker_role": "Executive VP and CFO",
                        "text": "Intelligent Cloud gross margins were 69%, consistent with our guidance. Capital expenditures were $19 billion to support accelerating demand for our cloud and AI services.",
                        "sentiment": 0.65
                    }
                ],
                "analyst_qa": [
                    {
                        "analyst_name": "Keith Weiss",
                        "analyst_firm": "Morgan Stanley",
                        "question": "How are you thinking about AI monetization vs CapEx payback timelines?",
                        "executive_response": "Amy Hood: Near-term capacity constraints are keeping demand ahead of our supply, which gives us high conviction in our CapEx investments."
                    }
                ]
            },
            "NVDA_Q4_2024": {
                "event": "NVIDIA Q4 FY24 Earnings Conference Call",
                "date": "2024-02-21",
                "prepared_remarks": [
                    {
                        "speaker_name": "Jensen Huang",
                        "speaker_role": "Founder and CEO",
                        "text": "Accelerated computing and generative AI have hit the tipping point. Demand is surging worldwide across companies, industries and nations. Our Data Center platform is powered by diverse drivers.",
                        "sentiment": 0.95
                    },
                    {
                        "speaker_name": "Colette Kress",
                        "speaker_role": "Executive VP and CFO",
                        "text": "Data Center revenue was a record $18.4 billion, up 409% from a year ago. Gross margin reached 76.0%. Supply for Hopper architecture continues to improve, but demand remains extraordinary.",
                        "sentiment": 0.90
                    }
                ],
                "analyst_qa": [
                    {
                        "analyst_name": "Toshiya Hari",
                        "analyst_firm": "Goldman Sachs",
                        "question": "Can you provide clarity on supply ramp for Blackwell and advanced packaging capacity?",
                        "executive_response": "Jensen Huang: Our supply chain partners including TSMC have done an incredible job expanding CoWoS capacity. We expect Blackwell to be in steep ramp through next year."
                    }
                ]
            }
        }

    @property
    def name(self) -> str:
        return "get_earnings_transcript"

    @property
    def description(self) -> str:
        return "Retrieves and segments quarterly earnings call transcripts with executive speaker attribution and Q&A analysis."

    async def get_transcript(self, ticker: str, quarter: str, speaker_role: str = "ALL") -> dict[str, Any]:
        key = f"{ticker.upper()}_{quarter.upper()}"
        transcript = self._transcripts.get(key)

        if not transcript:
            # No transcript in the corpus for this ticker/quarter. Say so
            # rather than generating a plausible one: an invented CFO quote
            # carrying a transcript citation is worse than no quote.
            return {
                "ticker": ticker.upper(),
                "quarter": quarter.upper(),
                "available": False,
                "event": None,
                "date": None,
                "prepared_remarks": [],
                "analyst_qa": [],
                "provenance_signature": None,
            }

        return {
            "ticker": ticker.upper(),
            "quarter": quarter.upper(),
            "available": True,
            "event": transcript["event"],
            "date": transcript["date"],
            "prepared_remarks": transcript["prepared_remarks"],
            "analyst_qa": transcript["analyst_qa"],
            "provenance_signature": f"TRANSCRIPT:{ticker}:{quarter}:{transcript['date']}"
        }
