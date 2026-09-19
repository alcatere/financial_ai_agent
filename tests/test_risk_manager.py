import pytest
from src.models.schemas import FinancialRecommendation, Rationale
from src.risk.risk_manager import RiskManager

RATIONALE = Rationale(technical_factors="t", fundamental_factors="f", sentiment_factors="s")


def make_rec(recommendation="BUY", confidence=80, allocation_pct=3.0):
    return FinancialRecommendation(
        recommendation=recommendation,
        asset="AAPL",
        confidence=confidence,
        rationale=RATIONALE,
        risks="none",
        suggested_allocation_pct=allocation_pct,
        suggested_position_size="3%",
        action="execute",
    )


@pytest.fixture
def risk_manager():
    return RiskManager(max_allocation_pct=5.0, min_confidence=70, max_daily_trades=3)


def test_hold_is_never_approved(risk_manager):
    rec = make_rec(recommendation="HOLD")
    decision = risk_manager.evaluate(rec, {}, {}, trades_today=0)
    assert decision.blocked


def test_low_confidence_is_blocked(risk_manager):
    rec = make_rec(confidence=50)
    decision = risk_manager.evaluate(rec, {}, {}, trades_today=0)
    assert decision.blocked
    assert any("Confidence" in r for r in decision.reasons)


def test_allocation_is_clamped_to_a_stricter_configured_cap():
    # Schema already hard-caps at 5%; a deployment can configure an even
    # stricter cap (e.g. 2%), which RiskManager must still enforce.
    strict_risk_manager = RiskManager(max_allocation_pct=2.0, min_confidence=70, max_daily_trades=3)
    rec = make_rec(allocation_pct=5.0)
    decision = strict_risk_manager.evaluate(rec, {}, {}, trades_today=0)
    assert decision.approved
    assert decision.allocation_pct == 2.0


def test_missing_market_data_blocks(risk_manager):
    rec = make_rec()
    decision = risk_manager.evaluate(rec, {"error": "no data"}, {}, trades_today=0)
    assert decision.blocked


def test_missing_fundamental_data_blocks(risk_manager):
    rec = make_rec()
    decision = risk_manager.evaluate(rec, {}, {"error": "no data"}, trades_today=0)
    assert decision.blocked


def test_daily_trade_limit_blocks(risk_manager):
    rec = make_rec()
    decision = risk_manager.evaluate(rec, {}, {}, trades_today=3)
    assert decision.blocked


def test_valid_recommendation_is_approved(risk_manager):
    rec = make_rec()
    decision = risk_manager.evaluate(rec, {}, {}, trades_today=0)
    assert decision.approved
    assert decision.allocation_pct == 3.0


def test_size_order_computes_whole_shares(risk_manager):
    qty = risk_manager.size_order(allocation_pct=5.0, account_equity=10_000, price=97.0)
    assert qty == 5  # floor(500 / 97) = 5


def test_size_order_zero_price_returns_zero(risk_manager):
    assert risk_manager.size_order(allocation_pct=5.0, account_equity=10_000, price=0) == 0


def test_size_order_zero_equity_returns_zero(risk_manager):
    assert risk_manager.size_order(allocation_pct=5.0, account_equity=0, price=100) == 0


def test_size_order_nan_price_returns_zero(risk_manager):
    assert risk_manager.size_order(allocation_pct=5.0, account_equity=10_000, price=float("nan")) == 0


def test_size_order_nan_equity_returns_zero(risk_manager):
    assert risk_manager.size_order(allocation_pct=5.0, account_equity=float("nan"), price=100) == 0


def test_evaluate_signal_hold_is_never_approved(risk_manager):
    rec = make_rec(recommendation="HOLD")
    decision = risk_manager.evaluate_signal(rec, {}, {})
    assert decision.blocked


def test_evaluate_signal_low_confidence_is_blocked(risk_manager):
    rec = make_rec(confidence=50)
    decision = risk_manager.evaluate_signal(rec, {}, {})
    assert decision.blocked


def test_evaluate_signal_missing_data_blocks(risk_manager):
    rec = make_rec()
    decision = risk_manager.evaluate_signal(rec, {"error": "no data"}, {})
    assert decision.blocked


def test_evaluate_signal_valid_recommendation_is_approved(risk_manager):
    rec = make_rec()
    decision = risk_manager.evaluate_signal(rec, {}, {})
    assert decision.approved
    assert decision.allocation_pct == 3.0


def test_evaluate_signal_has_no_daily_trade_limit_concept(risk_manager):
    # evaluate_signal takes no trades_today - it can never be blocked by
    # trade frequency, only by signal quality.
    rec = make_rec()
    decision = risk_manager.evaluate_signal(rec, {}, {})
    assert decision.approved
    assert not any("Daily trade limit" in r for r in decision.reasons)


def test_evaluate_hold_ignores_daily_trade_limit(risk_manager):
    # A HOLD short-circuits before the daily-trade-limit check, exactly as
    # evaluate_signal does - trades_today being at/over the cap must not
    # additionally show up in the reasons for a HOLD.
    rec = make_rec(recommendation="HOLD")
    decision = risk_manager.evaluate(rec, {}, {}, trades_today=999)
    assert decision.reasons == ["Recommendation is HOLD; no order to place."]
