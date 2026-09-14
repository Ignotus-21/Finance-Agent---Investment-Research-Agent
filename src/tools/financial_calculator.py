"""
Deterministic Financial Ratio Verification Engine.
Pure Python mathematical tool computing core fundamental ratios using Decimal precision.
Eliminates floating-point drift and prevents LLM numerical hallucinations.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from src.core.interfaces import BaseTool
from src.models.response import FinancialMetric


class FinancialCalculator(BaseTool):
    """
    Deterministic mathematical engine for fundamental equity analysis.
    Implements exact formulas conforming to docs/financial_kpi_specification.md.
    """

    @property
    def name(self) -> str:
        return "financial_calculator"

    @property
    def description(self) -> str:
        return (
            "Deterministic mathematical tool computing YoY revenue growth, operating margin compression in basis points, "
            "Free Cash Flow conversion, and Debt-to-Equity leverage with zero hallucination."
        )

    async def execute(self, **kwargs: Any) -> Any:
        return self.compute_all_metrics(**kwargs)

    @classmethod
    def to_decimal(cls, val: Any) -> Decimal:
        """Converts float/int/str to Decimal safely."""
        if val is None:
            return Decimal("0.0")
        return Decimal(str(val))

    @classmethod
    def calculate_yoy_growth(
        cls, current_val: float, prior_val: float | None, metric_name: str = "revenue"
    ) -> FinancialMetric | None:
        """
        Computes YoY Growth: ((Current - Prior) / Prior) * 100
        """
        if prior_val is None or prior_val <= 0:
            return None

        d_curr = cls.to_decimal(current_val)
        d_prior = cls.to_decimal(prior_val)

        # Growth % = ((d_curr - d_prior) / d_prior) * 100
        growth_pct = ((d_curr - d_prior) / d_prior) * Decimal("100.0")
        rounded = float(growth_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        return FinancialMetric(
            name=f"yoy_{metric_name}_growth_pct",
            display_name=f"YoY {metric_name.replace('_', ' ').title()} Growth Rate",
            value=rounded,
            unit="percentage",
            formula_applied=f"(({metric_name}_current - {metric_name}_prior) / {metric_name}_prior) * 100",
            prior_period_value=float(d_prior),
            current_period_value=float(d_curr),
            provenance_verified=True
        )

    @classmethod
    def calculate_operating_margins(
        cls,
        operating_income_curr: float,
        revenue_curr: float,
        operating_income_prior: float | None = None,
        revenue_prior: float | None = None,
    ) -> list[FinancialMetric]:
        """
        Computes Current Operating Margin (%) and Operating Margin Compression (bps).
        """
        metrics: list[FinancialMetric] = []
        if revenue_curr <= 0:
            return metrics

        d_op_curr = cls.to_decimal(operating_income_curr)
        d_rev_curr = cls.to_decimal(revenue_curr)

        margin_curr_pct = (d_op_curr / d_rev_curr) * Decimal("100.0")
        rounded_margin = float(margin_curr_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        metrics.append(
            FinancialMetric(
                name="operating_margin_current_pct",
                display_name="Operating Margin (EBIT)",
                value=rounded_margin,
                unit="percentage",
                formula_applied="(operating_income_current / revenue_current) * 100",
                prior_period_value=None,
                current_period_value=rounded_margin,
                provenance_verified=True
            )
        )

        if operating_income_prior is not None and revenue_prior and revenue_prior > 0:
            d_op_prior = cls.to_decimal(operating_income_prior)
            d_rev_prior = cls.to_decimal(revenue_prior)

            margin_prior_pct = (d_op_prior / d_rev_prior) * Decimal("100.0")
            # Compression in bps = (margin_prior - margin_curr) * 100
            compression_bps = (margin_prior_pct - margin_curr_pct) * Decimal("100.0")
            rounded_compression = float(compression_bps.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

            metrics.append(
                FinancialMetric(
                    name="operating_margin_compression_bps",
                    display_name="Operating Margin Compression",
                    value=rounded_compression,
                    unit="bps",
                    formula_applied="(operating_margin_prior - operating_margin_current) * 100",
                    prior_period_value=float(margin_prior_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                    current_period_value=rounded_margin,
                    provenance_verified=True
                )
            )

        return metrics

    @classmethod
    def calculate_free_cash_flow_conversion(
        cls, cash_from_ops: float, capex: float, net_income: float
    ) -> FinancialMetric | None:
        """
        Computes Free Cash Flow (FCF = Operating Cash - CapEx)
        and FCF Conversion % = (FCF / Net Income) * 100
        """
        d_ops = cls.to_decimal(cash_from_ops)
        d_capex = cls.to_decimal(abs(capex))
        d_ni = cls.to_decimal(net_income)

        fcf = d_ops - d_capex
        if d_ni <= Decimal("0.0"):
            return None

        conversion_pct = (fcf / d_ni) * Decimal("100.0")
        rounded_conversion = float(conversion_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        return FinancialMetric(
            name="free_cash_flow_conversion_pct",
            display_name="Free Cash Flow Conversion Ratio",
            value=rounded_conversion,
            unit="percentage",
            formula_applied="((cash_from_operations - capex) / net_income) * 100",
            prior_period_value=None,
            current_period_value=rounded_conversion,
            provenance_verified=True
        )

    @classmethod
    def calculate_debt_to_equity(
        cls, total_debt: float, shareholders_equity: float
    ) -> FinancialMetric | None:
        """
        Computes Debt-to-Equity Ratio = Total Debt / Shareholders' Equity
        """
        if shareholders_equity <= 0:
            return None

        d_debt = cls.to_decimal(total_debt)
        d_equity = cls.to_decimal(shareholders_equity)

        de_ratio = d_debt / d_equity
        rounded_de = float(de_ratio.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

        return FinancialMetric(
            name="debt_to_equity_ratio",
            display_name="Total Debt-to-Equity Ratio",
            value=rounded_de,
            unit="ratio_multiple",
            formula_applied="total_debt / shareholders_equity",
            prior_period_value=None,
            current_period_value=rounded_de,
            provenance_verified=True
        )

    def compute_all_metrics(self, sec_data: dict[str, Any]) -> list[FinancialMetric]:
        """Extracts primary figures from parsed SEC statements and returns all verified metrics."""
        metrics: list[FinancialMetric] = []
        inc = sec_data.get("income_statement", {})
        bal = sec_data.get("balance_sheet", {})
        cf = sec_data.get("cash_flow", {})

        # 1. YoY Revenue Growth
        rev_curr = inc.get("revenue_current")
        rev_prior = inc.get("revenue_prior")
        if rev_curr:
            rev_metric = self.calculate_yoy_growth(rev_curr, rev_prior, "revenue")
            if rev_metric:
                metrics.append(rev_metric)

        # 2. Operating Margin & Compression
        op_curr = inc.get("operating_income_current")
        op_prior = inc.get("operating_income_prior")
        if rev_curr and op_curr is not None:
            margin_metrics = self.calculate_operating_margins(op_curr, rev_curr, op_prior, rev_prior)
            metrics.extend(margin_metrics)

        # 3. Free Cash Flow Conversion
        ops_cash = cf.get("cash_from_operations")
        capex = cf.get("capital_expenditures")
        net_inc = inc.get("net_income")
        if ops_cash and capex is not None and net_inc:
            fcf_metric = self.calculate_free_cash_flow_conversion(ops_cash, capex, net_inc)
            if fcf_metric:
                metrics.append(fcf_metric)

        # 4. Debt to Equity Ratio
        total_debt = bal.get("total_debt")
        equity = bal.get("shareholders_equity")
        if total_debt is not None and equity:
            de_metric = self.calculate_debt_to_equity(total_debt, equity)
            if de_metric:
                metrics.append(de_metric)

        return metrics
