import yfinance as yf
from typing import Dict, List, Any

def get_recent_news(ticker: str) -> List[Dict[str, str]]:
    """Retrieve recent news headlines and summaries for a given ticker using yfinance."""
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news
        
        if not news_items:
            return [{"error": f"No news found for {ticker}."}]
        
        formatted_news = []
        # Return at most 5 recent news articles
        for item in news_items[:5]:
            formatted_news.append({
                "title": item.get("title", ""),
                "publisher": item.get("publisher", ""),
                "link": item.get("link", "")
            })
            
        return formatted_news
    except Exception as e:
        return [{"error": f"Failed to retrieve news data: {str(e)}"}]
