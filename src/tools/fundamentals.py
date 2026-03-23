import yfinance as yf
from typing import Dict, Any

def get_fundamental_data(ticker: str) -> Dict[str, Any]:
    """Retrieve fundamental data (P/E ratio, earnings, revenue) for a given ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        return {
            "forward_pe": info.get("forwardPE", "N/A"),
            "trailing_pe": info.get("trailingPE", "N/A"),
            "market_cap": info.get("marketCap", "N/A"),
            "profit_margins": info.get("profitMargins", "N/A"),
            "revenue_growth": info.get("revenueGrowth", "N/A"),
            "earnings_growth": info.get("earningsGrowth", "N/A"),
            "debt_to_equity": info.get("debtToEquity", "N/A"),
            "free_cashflow": info.get("freeCashflow", "N/A")
        }
    except Exception as e:
        return {"error": f"Failed to retrieve fundamental data: {str(e)}"}
