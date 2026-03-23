import pytest
from src.tools.market_data import get_market_data
from src.tools.fundamentals import get_fundamental_data
from src.tools.sentiment import get_recent_news

def test_market_data_valid_ticker():
    # AAPL is a highly traded valid ticker
    data = get_market_data("AAPL")
    assert "error" not in data
    assert "current_price" in data
    assert "average_daily_volume_1mo" in data
    assert "trend_1mo" in data

def test_market_data_invalid_ticker():
    data = get_market_data("INVALID_TICKER_123")
    # yfinance often returns an edge case empty set for invalid tickers
    assert "error" in data or data.get("current_price") is None

def test_fundamental_data():
    data = get_fundamental_data("AAPL")
    assert "error" not in data
    assert "forward_pe" in data
    assert "market_cap" in data

def test_sentiment_data():
    # Note: Sometimes news might be empty depending on Yahoo Finance behavior, 
    # but for AAPL there should always be news.
    news = get_recent_news("AAPL")
    assert isinstance(news, list)
    if len(news) > 0 and "error" not in news[0]:
        assert "title" in news[0]
        assert "link" in news[0]
