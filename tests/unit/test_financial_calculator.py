"""
Unit tests for Deterministic Financial Calculator.
Asserts mathematical precision, IEEE 754 float safety, and zero-denominator handling.
"""

from src.tools.financial_calculator import FinancialCalculator


def test_yoy_revenue_growth_calculation():
    """Verify YoY growth rate precision and positive/negative handling."""
    # Positive growth
    m1 = FinancialCalculator.calculate_yoy_growth(current_val=391035000000.0, prior_val=383285000000.0, metric_name="revenue")
    assert m1 is not None
    assert m1.value == 2.02
    assert m1.unit == "percentage"
    assert m1.provenance_verified is True

    # Negative growth
    m2 = FinancialCalculator.calculate_yoy_growth(current_val=50000.0, prior_val=100000.0, metric_name="revenue")
    assert m2 is not None
    assert m2.value == -50.0

    # Zero prior denominator
    m3 = FinancialCalculator.calculate_yoy_growth(current_val=50000.0, prior_val=0.0)
    assert m3 is None


def test_operating_margins_and_compression():
    """Verify operating margin and basis points compression/expansion."""
    metrics = FinancialCalculator.calculate_operating_margins(
        operating_income_curr=123216000000.0,
        revenue_curr=391035000000.0,
        operating_income_prior=114301000000.0,
        revenue_prior=383285000000.0
    )
    assert len(metrics) == 2
    curr_margin = metrics[0]
    compression = metrics[1]

    # Current margin: 123216 / 391035 * 100 = 31.51%
    assert curr_margin.value == 31.51
    assert curr_margin.unit == "percentage"

    # Prior margin was 29.82%, so compression is -169.1 bps (meaning expansion!)
    assert compression.unit == "bps"
    assert compression.value < 0  # Expansion


def test_free_cash_flow_conversion():
    """Verify FCF conversion = (Cash from Ops - CapEx) / Net Income * 100."""
    # Valid positive net income
    fcf_m = FinancialCalculator.calculate_free_cash_flow_conversion(
        cash_from_ops=118260000000.0,
        capex=9452000000.0,
        net_income=93736000000.0
    )
    assert fcf_m is not None
    # FCF = 118260 - 9452 = 108808; 108808 / 93736 * 100 = 116.08%
    assert fcf_m.value == 116.08

    # Negative net income handling
    fcf_neg = FinancialCalculator.calculate_free_cash_flow_conversion(
        cash_from_ops=10000.0,
        capex=2000.0,
        net_income=-5000.0
    )
    assert fcf_neg is None


def test_debt_to_equity_leverage():
    """Verify Total Debt to Equity ratio multiple."""
    de_m = FinancialCalculator.calculate_debt_to_equity(
        total_debt=106629000000.0,
        shareholders_equity=66802000000.0
    )
    assert de_m is not None
    assert de_m.value == 1.596
    assert de_m.unit == "ratio_multiple"

    # Negative equity deficit
    de_neg = FinancialCalculator.calculate_debt_to_equity(
        total_debt=10000.0,
        shareholders_equity=-500.0
    )
    assert de_neg is None


def test_margin_pct_uses_decimal_half_up_not_float():
    """1.005 / 100 is 1.00499... in binary float; Decimal half-up must give 1.01."""
    assert FinancialCalculator.calculate_margin_pct(1.005, 100.0) == 1.01
    assert FinancialCalculator.calculate_margin_pct(10.0, 0.0) is None


def test_adk_ratio_tool_routes_through_decimal_engine():
    """The ADK tool must agree with the Decimal engine, not with float arithmetic."""
    import json

    from src.agents.adk_agent import compute_financial_ratios

    out = json.loads(compute_financial_ratios(revenue=100.0, net_income=1.005, operating_income=1.005))
    assert out["operating_margin_pct"] == 1.01
    assert out["net_margin_pct"] == 1.01

    zero_rev = json.loads(compute_financial_ratios(revenue=0.0, net_income=1.0, operating_income=1.0))
    assert zero_rev["operating_margin_pct"] is None
