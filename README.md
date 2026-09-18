# Financial AI Agent

An AI-powered financial analysis agent that turns fundamental, technical, and sentiment data into risk-managed trading recommendations, and can propose (or, once you enable it, place) orders through **Interactive Brokers**.

## Why Interactive Brokers, not GBM

This project originally targeted GBM. GBM does not publish an official trading API — only reverse-engineered community libraries exist, and they explicitly warn about breaking without notice and possibly violating GBM's Terms of Service. Interactive Brokers offers a free, official, actively-maintained API, accepts Mexican residents, and gives direct access to both the Bolsa Mexicana de Valores (BMV) and US markets, so it's the execution broker here.

**Current scope note:** the code as implemented only trades USD-denominated, SMART-routed US-listed symbols (see `EXCHANGE`/`CURRENCY` in `src/broker/ibkr.py`). BMV/MXN trading is a capability of an IBKR account in general, but isn't wired up in this codebase yet.

## Features
- **Data Retrieval Tools**: real-time price trends, volumes, P/E ratios, earnings growth, and recent news via `yfinance`.
- **Intelligent Analysis**: ReAct-style processing powered by OpenRouter (Anthropic models) and LangChain, output forced into a strict Pydantic schema.
- **Deterministic Risk Manager** (`src/risk/risk_manager.py`): re-checks the LLM's output in plain Python — confidence ≥ 70%, allocation capped at 5% (configurable, stricter than the schema's own 5% ceiling if you want), missing/errored data blocks the trade, and a daily trade-count limit. This runs regardless of what the LLM claims.
- **Paper trading first**: targets IB Gateway's paper-trading account by default (`TRADING_MODE=paper`). Nothing touches real money until you deliberately flip this.
- **Human-in-the-loop execution via Telegram**: every proposed order is sent to you on Telegram; you approve or reject it before it's ever sent to the broker. The same code path supports a fully autonomous mode later via one config flag (`EXECUTION_MODE=autonomous`) — no rework needed.
- **No broker credentials stored here**: the agent connects to an IB Gateway/TWS instance that *you* start and log into yourself. IBKR's own app owns your login and 2FA.

## Tech Stack
- **Python 3.10+**
- **LangChain** (orchestration & prompts) + **OpenRouter/Anthropic** (LLM)
- **YFinance & Pandas** (market/fundamental data)
- **Pydantic** (strict output schema)
- **ib_async** (Interactive Brokers API client)
- **Telegram Bot API** (notifications + confirmations, via `requests`)

## Setup & Installation

1. **Clone the repository and install dependencies:**
   ```bash
   git clone git@github.com:alcatere/financial_ai_agent.git
   cd financial_ai_agent
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

2. **Install and start IB Gateway** (free, from Interactive Brokers): log in with your IBKR paper-trading account, and leave it running. This agent never sees your IBKR password — it just connects to the already-authenticated Gateway on `localhost`.

3. **Create a Telegram bot**: message [@BotFather](https://t.me/BotFather) to get a `TELEGRAM_BOT_TOKEN`, send your bot any message, then call `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `TELEGRAM_CHAT_ID`.

4. **Configure `.env`** (see the file for the full list): at minimum set `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`. `TRADING_MODE=paper` and `EXECUTION_MODE=confirm` are the safe defaults and are what you should run with until you trust the system.

## Usage

The workflow is split into two steps so it can later be driven by cron without ever blocking on a Telegram reply:

```bash
# 1. Analyze a ticker. If the risk manager approves a BUY/SELL, you'll get a
#    Telegram message with an order id.
python main.py analyze --ticker AAPL

# 2. Reply on Telegram with /confirm_<id> or /reject_<id>, then run:
python main.py check-confirmations
```

### Running on a schedule (cron)
Once you're comfortable running this unattended for the *analysis* step, something like:
```cron
# Analyze a watchlist every weekday at 9:00 (before US market open)
0 9 * * 1-5 cd /path/to/financial_ai_agent && .venv/bin/python main.py analyze --ticker AAPL
# Check for Telegram confirmations every 2 minutes
*/2 * * * * cd /path/to/financial_ai_agent && .venv/bin/python main.py check-confirmations
```
IB Gateway still needs to be running and logged in for either command to reach the broker.

### Going autonomous (later, deliberately)
Set `EXECUTION_MODE=autonomous` in `.env` to have risk-approved orders execute immediately instead of waiting for a Telegram confirmation — you'll still be notified after the fact. Only do this once you've watched the confirm-mode behavior for a while and trust it.

### Going live (real money — do this deliberately)
Everything defaults to `TRADING_MODE=paper`, which talks to IB Gateway's paper account (port 4002). To trade with real money, point IB Gateway at your live account, log into *that*, and set `TRADING_MODE=live` (this switches to port 4001). The app refuses to start if `TRADING_MODE=live` is combined with the paper port, as a guardrail against a copy-pasted config mistake.

## Verification / Tests
Unit tests cover the risk manager, order store, and Telegram message parsing without needing a live IB Gateway connection or LLM calls:
```bash
pytest -v
```
