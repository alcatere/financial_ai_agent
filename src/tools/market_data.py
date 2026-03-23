import yfinance as yf
import pandas as pd
from typing import Dict, Any

def get_market_data(ticker: str) -> Dict[str, Any]:
    """Retrieve market data (price, volume, trends) for a given ticker."""
    try:
        stock = yf.Ticker(ticker)
        # Get 1 month of historical data to compute simple trends
        hist = stock.history(period="1mo")
        if hist.empty:
            return {"error": f"No market data found for {ticker}."}

        current_price = hist["Close"].iloc[-1]
        avg_volume = hist["Volume"].mean()
        # Simple trend indication: comparison of current price vs 1-month average
        price_1mo_avg = hist["Close"].mean()
        trend = "Bullish" if current_price > price_1mo_avg else "Bearish"

        # Additional basic info (52-week highs/lows)
        info = stock.info
        fifty_two_week_high = info.get("fiftyTwoWeekHigh", "N/A")
        fifty_two_week_low = info.get("fiftyTwoWeekLow", "N/A")

        return {
            "current_price": current_price,
            "average_daily_volume_1mo": avg_volume,
            "trend_1mo": trend,
            "fifty_two_week_high": fifty_two_week_high,
            "fifty_two_week_low": fifty_two_week_low,
        }
    except Exception as e:
        return {"error": f"Failed to retrieve market data: {str(e)}"}
