import time

import pytest
from src.models.schemas import FinancialRecommendation, Rationale
from src.pipeline import _analyze_with_timeout, build_digest_messages, format_digest_line
from src.risk.risk_manager import RiskDecision

RATIONALE = Rationale(
    technical_factors="uptrend", fundamental_factors="strong earnings", sentiment_factors="positive news"
)


def make_rec(recommendation="BUY", confidence=80):
    return FinancialRecommendation(
        recommendation=recommendation,
        asset="AAPL",
        confidence=confidence,
        rationale=RATIONALE,
        risks="none",
        suggested_allocation_pct=3.0,
        suggested_position_size="3%",
        action="execute",
    )


def test_error_line():
    line = format_digest_line("AAPL", None, None, error="timeout")
    assert "AAPL" in line
    assert "no se pudo analizar" in line
    assert "timeout" in line


def test_hold_line():
    rec = make_rec(recommendation="HOLD")
    decision = RiskDecision(approved=False, allocation_pct=0.0, reasons=["Recommendation is HOLD; no order to place."])
    line = format_digest_line("AAPL", rec, decision)
    assert "mantente" in line
    assert "estable" in line


def test_hold_caused_by_missing_data_is_not_reported_as_stable():
    rec = make_rec(recommendation="HOLD")
    decision = RiskDecision(
        approved=False,
        allocation_pct=0.0,
        reasons=["Market data unavailable: No market data found for AAPL.", "Recommendation is HOLD; no order to place."],
    )
    line = format_digest_line("AAPL", rec, decision, data_unavailable=True)
    assert "sin datos suficientes" in line
    assert "estable" not in line
    assert "Market data unavailable" in line


def test_hold_without_data_unavailable_flag_reads_as_stable_even_with_matching_wording():
    # data_unavailable is an explicit flag, not inferred from reason text -
    # a reason string that happens to contain "unavailable" must not flip
    # the branch on its own.
    rec = make_rec(recommendation="HOLD")
    decision = RiskDecision(
        approved=False, allocation_pct=0.0,
        reasons=["Some unrelated note mentions unavailable in passing.", "Recommendation is HOLD; no order to place."],
    )
    line = format_digest_line("AAPL", rec, decision, data_unavailable=False)
    assert "estable" in line
    assert "sin datos suficientes" not in line


def test_approved_buy_line():
    rec = make_rec(recommendation="BUY", confidence=85)
    decision = RiskDecision(approved=True, allocation_pct=3.0, reasons=[])
    line = format_digest_line("AAPL", rec, decision)
    assert "COMPRA" in line
    assert "85%" in line


def test_approved_sell_line():
    rec = make_rec(recommendation="SELL", confidence=90)
    decision = RiskDecision(approved=True, allocation_pct=3.0, reasons=[])
    line = format_digest_line("AAPL", rec, decision)
    assert "VENDE" in line
    assert "90%" in line


def test_blocked_signal_line_shows_reasons():
    rec = make_rec(recommendation="BUY", confidence=50)
    decision = RiskDecision(approved=False, allocation_pct=0.0, reasons=["Confidence 50% is below the 70% minimum required to execute."])
    line = format_digest_line("AAPL", rec, decision)
    assert "sin acción clara" in line
    assert "Confidence 50%" in line
    assert "COMPRA" not in line


def test_decision_none_without_error_raises():
    rec = make_rec(recommendation="BUY")
    with pytest.raises(ValueError):
        format_digest_line("AAPL", rec, None)


def test_decision_none_for_hold_also_raises():
    rec = make_rec(recommendation="HOLD")
    with pytest.raises(ValueError):
        format_digest_line("AAPL", rec, None)


def test_recommendation_none_without_error_raises():
    decision = RiskDecision(approved=True, allocation_pct=3.0, reasons=[])
    with pytest.raises(ValueError):
        format_digest_line("AAPL", None, decision)


def test_ticker_with_markdown_chars_is_escaped():
    rec = make_rec(recommendation="HOLD")
    decision = RiskDecision(approved=False, allocation_pct=0.0, reasons=["Recommendation is HOLD; no order to place."])
    line = format_digest_line("MY_TICKER", rec, decision)
    assert "MY\\_TICKER" in line


def test_long_reason_is_truncated():
    rationale = Rationale(technical_factors="t", fundamental_factors="x" * 500, sentiment_factors="s")
    rec = FinancialRecommendation(
        recommendation="BUY", asset="AAPL", confidence=85, rationale=rationale, risks="none",
        suggested_allocation_pct=3.0, suggested_position_size="3%", action="execute",
    )
    decision = RiskDecision(approved=True, allocation_pct=3.0, reasons=[])
    line = format_digest_line("AAPL", rec, decision)
    assert len(line) < 300
    assert "…" in line


def test_reason_with_markdown_chars_is_escaped():
    rationale = Rationale(technical_factors="t", fundamental_factors="growth_rate is *strong*", sentiment_factors="s")
    rec = FinancialRecommendation(
        recommendation="BUY", asset="AAPL", confidence=85, rationale=rationale, risks="none",
        suggested_allocation_pct=3.0, suggested_position_size="3%", action="execute",
    )
    decision = RiskDecision(approved=True, allocation_pct=3.0, reasons=[])
    line = format_digest_line("AAPL", rec, decision)
    assert "growth\\_rate is \\*strong\\*" in line


def test_analyze_with_timeout_raises_on_hang(monkeypatch):
    def slow_analyze(ticker, config):
        time.sleep(5)
        return "should not get here"

    monkeypatch.setattr("src.pipeline.analyze_asset", slow_analyze)
    with pytest.raises(TimeoutError):
        _analyze_with_timeout("AAPL", config=None, timeout_seconds=0.1)


def test_analyze_with_timeout_returns_value_when_fast(monkeypatch):
    monkeypatch.setattr("src.pipeline.analyze_asset", lambda ticker, config: "result")
    assert _analyze_with_timeout("AAPL", config=None, timeout_seconds=1) == "result"


def test_build_digest_messages_single_chunk_for_short_content():
    messages = build_digest_messages("*Header*", ["line one", "line two"])
    assert len(messages) == 1
    assert messages[0] == "*Header*\n\nline one\n\nline two"


def test_build_digest_messages_splits_when_over_the_limit():
    long_lines = [f"ticker {i}: " + ("x" * 500) for i in range(20)]
    messages = build_digest_messages("*Header*", long_lines)
    assert len(messages) > 1
    for msg in messages:
        assert len(msg) < 4096
        assert "parte" in msg
    # every original line shows up somewhere across the chunks
    joined = "\n\n".join(messages)
    for line in long_lines:
        assert line in joined


def test_analyze_with_timeout_reraises_underlying_exception(monkeypatch):
    def failing_analyze(ticker, config):
        raise ValueError("boom")

    monkeypatch.setattr("src.pipeline.analyze_asset", failing_analyze)
    with pytest.raises(ValueError, match="boom"):
        _analyze_with_timeout("AAPL", config=None, timeout_seconds=1)


def test_analyze_with_timeout_wraps_non_exception_base_exception(monkeypatch):
    # A BaseException that isn't an Exception (e.g. SystemExit) must come out
    # wrapped in an ordinary Exception, so a caller's `except Exception` stays
    # sufficient for full per-ticker isolation - it must never need to widen
    # to `except BaseException`, which would also swallow Ctrl+C.
    def exits(ticker, config):
        raise SystemExit("bye")

    monkeypatch.setattr("src.pipeline.analyze_asset", exits)
    with pytest.raises(Exception) as exc_info:
        _analyze_with_timeout("AAPL", config=None, timeout_seconds=1)
    assert not isinstance(exc_info.value, SystemExit)
