# Financial AI Agent

An AI-powered financial analysis and trading assistant designed to support investment decisions in equity markets. Focuses deeply on retrieving fundamental, technical, and sentiment data to provide strict, risk-managed trading recommendations.

## Features
- **Data Retrieval Tools**: Fetches real-time price trends, volumes, P/E ratios, earnings growth, and recent news articles seamlessly using `yfinance`.
- **Intelligent Analysis**: ReAct-style processing powered by OpenRouter (Anthropic Models) and LangChain. 
- **Strict Risk Management**: The agent operates under mandated guidelines:
  - Never allocate more than 5% of a portfolio to a single asset.
  - Recommends HOLD or NO ACTION when uncertainty is high or data is lacking.
  - Ensures a confidence baseline for any explicit BUY/SELL recommendations.
- **Deterministic Output**: Forcibly formats LLM insights into a strictly typed Pydantic JSON structure ensuring machine-readable predictability.

## Tech Stack
- **Python 3** (configured with `uv` and `venv`)
- **LangChain** (Orchestration & Prompts)
- **OpenRouter & Anthropic** (LLM Intelligence)
- **YFinance & Pandas** (Data Engineering)
- **Pydantic** (Output Verification)

## Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone git@github.com:alcatere/financial_ai_agent.git
   cd financial_ai_agent
   ```

2. **Set up the Virtual Environment & Dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install uv
   uv pip install langchain-openai langchain-core yfinance pydantic python-dotenv pytest pandas
   ```

3. **Configure the Environment Variables:**
   Rename `.env.example` to `.env` and provide your OpenRouter API Key:
   ```env
   OPENROUTER_API_KEY="your_api_key_here"
   OPENROUTER_MODEL="anthropic/claude-3.5-sonnet"
   ```

## Usage

Simply run the agent via the command line interface, providing the ticker symbol of the asset you wish to analyze.

```bash
python main.py --ticker AAPL
```

The output will structure cleanly into:
- **Action** (BUY, SELL, HOLD)
- **Asset**
- **Confidence** (%)
- **Rationale** (Technical, Fundamental, Sentiment)
- **Risks**
- **Suggested Position Size**
- **Execution Strategy**

## Verification / Tests
You can verify the data extraction tools work natively without calling the LLM by executing tests:
```bash
PYTHONPATH=. pytest tests/test_tools.py -v
```
