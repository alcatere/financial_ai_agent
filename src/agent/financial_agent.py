from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import requests
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from src.config import Config
from src.models.schemas import FinancialRecommendation
from src.tools.market_data import get_market_data
from src.tools.fundamentals import get_fundamental_data
from src.tools.sentiment import get_recent_news
import json


@dataclass
class AnalysisResult:
    recommendation: FinancialRecommendation
    market_data: Dict[str, Any]
    fundamental_data: Dict[str, Any]
    news_data: List[Dict[str, str]]

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

MAX_OUTPUT_TOKENS = 1000
TEMPERATURE = 0.1  # low for consistent, non-creative analysis
LLM_TIMEOUT_MARGIN_SECONDS = 20
LLM_TIMEOUT_FLOOR_SECONDS = 30


def llm_timeout_seconds(config: Config) -> int:
    """Client-level timeout for the LLM call, deliberately *shorter* than
    the per-ticker thread timeout in src/pipeline.py.

    The thread timeout only stops *waiting*; it can't cancel the request.
    The HTTP client timeout, firing first, closes the connection - and
    Ollama aborts generation when its client disconnects, which frees the
    (single, shared) local GPU for the next ticker. If the two timeouts
    were equal the client one would never fire, and one slow ticker's
    orphaned generation would cascade into timeouts for the whole
    watchlist.
    """
    return max(LLM_TIMEOUT_FLOOR_SECONDS, config.analysis_timeout_seconds - LLM_TIMEOUT_MARGIN_SECONDS)


def llm_unreachable_reason(config: Config) -> Optional[str]:
    """Cheap preflight for the local provider. Returns a human-readable
    reason if the LLM can't be reached, else None.

    Ollama is a locally-running app that may simply not be open (e.g. at
    7 AM after a reboot). Without this check, that shows up as every
    ticker in the digest failing with the same obscure connection error
    instead of one clear, actionable message. Hosted providers are not
    checked - a failure there surfaces per ticker and is not a "you
    forgot to start something" situation.
    """
    if config.llm_provider != "ollama":
        return None
    try:
        requests.get(f"{config.ollama_base_url}/api/tags", timeout=5).raise_for_status()
    except requests.RequestException as e:
        return (
            f"Ollama is not reachable at {config.ollama_base_url} ({e.__class__.__name__}). "
            f"Is the Ollama app / `ollama serve` running? Or set LLM_PROVIDER=openrouter."
        )
    return None


def get_llm(config: Config):
    """Selected by LLM_PROVIDER."""
    timeout = llm_timeout_seconds(config)
    if config.llm_provider == "ollama":
        return ChatOllama(
            model=config.ollama_model,
            base_url=config.ollama_base_url,
            temperature=TEMPERATURE,
            num_predict=MAX_OUTPUT_TOKENS,
            # JSON mode: the model can only emit valid JSON, which is exactly
            # what PydanticOutputParser needs and removes the most common
            # local-model failure (markdown fences / prose around the JSON).
            format="json",
            # Thinking models (e.g. qwen3) would otherwise spend their token
            # budget on reasoning traces; the digest needs the structured
            # answer within a bounded latency, not a visible chain of thought.
            reasoning=False,
            client_kwargs={"timeout": timeout},
        ).bind(
            # ChatOllama streams by default, and with streaming the httpx
            # timeout is a per-chunk *read* timeout: a slow but steady
            # generation would never trip it. Non-streaming, Ollama sends
            # nothing until it's done, so the timeout bounds the whole call.
            stream=False,
        )
    return ChatOpenAI(
        model=config.openrouter_model,
        openai_api_key=config.openrouter_api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=TEMPERATURE,
        timeout=timeout,
    )

def analyze_asset(ticker: str, config: Config) -> AnalysisResult:
    """End-to-end pipeline: Fetch data -> Prompt LLM -> Parse Output"""
    print(f"[*] Fetching market data for {ticker}...")
    market_data = get_market_data(ticker)
    
    print(f"[*] Fetching fundamental data for {ticker}...")
    fundamental_data = get_fundamental_data(ticker)
    
    print(f"[*] Fetching recent news for {ticker}...")
    news_data = get_recent_news(ticker)

    parser = PydanticOutputParser(pydantic_object=FinancialRecommendation)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "Analyze the following asset and provide your strict recommendation based on the current data.\n\n"
                  "Asset: {ticker}\n"
                  "Market Data: {market_data}\n"
                  "Fundamental Data: {fundamental_data}\n"
                  "Recent News: {news_data}\n\n"
                  "{format_instructions}")
    ])

    llm = get_llm(config)
    # Explicitly parsing the output to ensure the schema is strictly followed
    chain = prompt | llm | parser
    
    print(f"[*] Analyzing data securely with AI...")
    result = chain.invoke({
        "ticker": ticker,
        "market_data": json.dumps(market_data),
        "fundamental_data": json.dumps(fundamental_data),
        "news_data": json.dumps(news_data),
        "format_instructions": parser.get_format_instructions()
    })
    
    return AnalysisResult(
        recommendation=result,
        market_data=market_data,
        fundamental_data=fundamental_data,
        news_data=news_data,
    )
