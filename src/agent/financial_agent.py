import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.models.schemas import FinancialRecommendation
from src.tools.market_data import get_market_data
from src.tools.fundamentals import get_fundamental_data
from src.tools.sentiment import get_recent_news
import json

load_dotenv()

SYSTEM_PROMPT = """
You are an AI-powered financial analysis and trading assistant designed to support investment decisions in equity markets.
Your primary objective is to analyze financial data, market signals, and news in order to generate well-reasoned trading recommendations.

CORE RESPONSIBILITIES
1. Analyze provided data sources: Market data (price, volume, trends), Fundamental data (metrics), News and sentiment.
2. Generate clear, structured insights: Identify opportunities, provide reasoning, and quantify confidence.

DECISION-MAKING PROCESS
1. Analyze signals (Technical, Fundamental, Sentiment).
2. Form a hypothesis based on the retrieved data.
3. Validate against risk constraints.
4. Produce final output using the mandated JSON schema.

RISK MANAGEMENT RULES (STRICT)
- Never allocate more than 5% of the portfolio to a single asset.
- Avoid trading in highly volatile or uncertain conditions.
- Do not execute trades if confidence is below 70%.
- Always consider stop-loss levels in your rationale.
- Prevent excessive trading (overtrading).
- If uncertain, DO NOT EXECUTE (Recommend HOLD or NO ACTION).
- Never hallucinate financial data. If data is missing (e.g. 'N/A'), explicitly state it and prefer 'no action'.
"""

def get_llm():
    # We use ChatOpenAI connected to OpenRouter for Anthropic models
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable not set")
    
    return ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        max_tokens=1000,
        temperature=0.1 # Low temperature for accurate analysis
    )

def analyze_asset(ticker: str) -> FinancialRecommendation:
    """End-to-end pipeline: Fetch data -> Prompt LLM -> Parse Output"""
    print(f"[*] Fetching market data for {ticker}...")
    market_data = get_market_data(ticker)
    
    print(f"[*] Fetching fundamental data for {ticker}...")
    fundamental_data = get_fundamental_data(ticker)
    
    print(f"[*] Fetching recent news for {ticker}...")
    news_data = get_recent_news(ticker)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "Analyze the following asset and provide your strict recommendation based on the current data.\n\n"
                  "Asset: {ticker}\n"
                  "Market Data: {market_data}\n"
                  "Fundamental Data: {fundamental_data}\n"
                  "Recent News: {news_data}\n\n"
                  "Output strictly matching the requested JSON format.")
    ])

    llm = get_llm()
    # Ensure structured output
    structured_llm = llm.with_structured_output(FinancialRecommendation)
    
    chain = prompt | structured_llm
    
    print(f"[*] Analyzing data securely with AI...")
    result = chain.invoke({
        "ticker": ticker,
        "market_data": json.dumps(market_data),
        "fundamental_data": json.dumps(fundamental_data),
        "news_data": json.dumps(news_data)
    })
    
    return result
