"""
Financial Domain Scope Classifier.
Ensures the system only accepts queries within the institutional equity research domain.
Rejects out-of-scope requests such as stock price speculation, trading execution, or general creative generation.
"""

import re
from typing import Tuple


class ScopeClassifier:
    """Enforces boundaries between permitted equity research and prohibited requests."""

    # Prohibited intent patterns
    PROHIBITED_INTENTS = [
        # Stock price speculation & fortune telling
        (r"(?i)\b(will\s+(?:the\s+)?stock\s+(?:hit|reach|drop|rise)|price\s+target\s+prediction|option\s+strike\s+price\s+to\s+buy|get\s+rich)\b", 
         "Stock price speculation and quantitative trading advice are prohibited by system governance."),
        
        # Algorithmic trade execution
        (r"(?i)\b(buy\s+\d+\s+shares|sell\s+\d+\s+shares|execute\s+order|transmit\s+(?:to\s+)?broker|place\s+(?:a\s+)?trade)\b", 
         "Trade execution and direct brokerage order routing are strictly out-of-scope."),
        
        # Non-financial creative or code generation requests
        (r"(?i)\b(write\s+(?:a\s+)?(?:story|poem|song|essay|fiction)|act\s+as\s+my\s+grandmother)\b", 
         "Creative writing and non-financial roleplay are outside the system domain.")
    ]

    # Required domain indicators for ambiguous queries
    FINANCIAL_ANCHOR_TERMS = [
        "revenue", "sales", "margin", "income", "profit", "ebitda", "cash flow", "fcf",
        "debt", "equity", "leverage", "capex", "10-k", "10-q", "8-k", "filing", "transcript",
        "earnings", "quarter", "cfo", "ceo", "guidance", "headwinds", "valuation", "ratio",
        "balance sheet", "sec", "xbrl", "shares", "dividend", "repurchase", "research", "stock"
    ]

    @classmethod
    def evaluate_scope(cls, prompt: str) -> Tuple[bool, str]:
        """
        Evaluates whether the prompt is strictly within financial equity research scope.
        Returns: (is_in_scope, message)
        """
        # 1. Check prohibited intent patterns
        for pattern, explanation in cls.PROHIBITED_INTENTS:
            if re.search(pattern, prompt):
                return False, explanation

        # 2. Check for at least one financial domain anchor term
        prompt_lower = prompt.lower()
        if not any(term in prompt_lower for term in cls.FINANCIAL_ANCHOR_TERMS):
            return False, "Query lacks financial domain context. The IRA system only processes corporate fundamental research."

        return True, "Query is within financial equity research scope."
