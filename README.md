# Financial AI Agent

An AI-powered financial analysis agent that turns fundamental, technical, and sentiment data into risk-managed trading recommendations.

**Current mode: advisory only.** Once a day it analyzes a watchlist of stocks and sends you one Telegram message with a verdict per ticker — buy, sell, or stay put — and you execute manually in your own broker (in this case, **GBM**). It never places an order or touches a broker account. A separate, not-yet-enabled phase (below) adds automated execution via Interactive Brokers for later.

## Features
- **Data Retrieval Tools**: real-time price trends, volumes, P/E ratios, earnings growth, and recent news via `yfinance` — works for both US tickers (`AAPL`) and BMV/Mexican tickers (`WALMEX.MX`), so your watchlist can mix what you actually trade on GBM with anything else.
- **Intelligent Analysis**: ReAct-style processing powered by OpenRouter (Anthropic models) and LangChain, output forced into a strict Pydantic schema.
- **Deterministic Risk Manager** (`src/risk/risk_manager.py`): re-checks the LLM's output in plain Python before it's ever reported as an actionable signal — confidence ≥ 70% and no missing/errored data. This runs regardless of what the LLM claims.
- **Daily digest via Telegram**: one message a day, one line per watchlist ticker, so a quiet day still confirms the system is alive.

## Tech Stack
- **Python 3.10+**
- **LangChain** (orchestration & prompts) + **OpenRouter/Anthropic** (LLM)
- **YFinance & Pandas** (market/fundamental data)
- **Pydantic** (strict output schema)
- **Telegram Bot API** (notifications, via `requests`)

## Setup & Installation

1. **Clone the repository and install dependencies:**
   ```bash
   git clone git@github.com:alcatere/financial_ai_agent.git
   cd financial_ai_agent
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

2. **Create a Telegram bot**: message [@BotFather](https://t.me/BotFather) to get a `TELEGRAM_BOT_TOKEN`, send your bot any message, then call `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `TELEGRAM_CHAT_ID`.

3. **Configure `.env`**: at minimum set `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`. Set `WATCHLIST` to the tickers you want analyzed daily (comma-separated, e.g. `AAPL,MSFT,WALMEX.MX,GFNORTEO.MX,AMXL.MX`) — mix BMV (`.MX`) and US tickers freely.

## Usage

```bash
python main.py daily-digest
```

This analyzes every ticker in `WATCHLIST` and sends one Telegram message like:

```
Resumen diario — 2026-09-18

🟢 AAPL: COMPRA (confianza 85%). Strong earnings growth and expanding margins.
➡️ WALMEX.MX: mantente, está estable. Revenue growth in line with expectations.
🔴 GFNORTEO.MX: VENDE (confianza 78%). Deteriorating credit metrics.
➡️ AMXL.MX: sin acción clara (Confidence 55% is below the 70% minimum required to execute.)
```

### Running it automatically, once a day (macOS `launchd`)

A `launchd` user-agent template lives at `launchd/com.financialaiagent.dailydigest.plist`. To install it (already done on this machine; use these steps again if you move the repo or reinstall):

```bash
REPO_ROOT="$(pwd)"
sed -e "s|__REPO_ROOT__|${REPO_ROOT}|g" -e "s|__HOME__|${HOME}|g" \
  launchd/com.financialaiagent.dailydigest.plist \
  > ~/Library/LaunchAgents/com.financialaiagent.dailydigest.plist
launchctl load -w ~/Library/LaunchAgents/com.financialaiagent.dailydigest.plist
```

It fires at **7:00 AM local time** (`StartCalendarInterval`, which uses the Mac's own clock/timezone — make sure your system timezone is set to Mexico City). Output and errors are logged to `~/Library/Logs/financial-ai-agent-digest.log`.

To check it's loaded: `launchctl list | grep financialaiagent`. To trigger it immediately for testing (without waiting for 7 AM): `launchctl start com.financialaiagent.dailydigest`, then check the log file. To stop/remove it entirely:
```bash
launchctl unload -w ~/Library/LaunchAgents/com.financialaiagent.dailydigest.plist
rm ~/Library/LaunchAgents/com.financialaiagent.dailydigest.plist
```

## Verification / Tests
Unit tests cover the risk manager, config parsing, order store, digest formatting, and Telegram message parsing without needing a live LLM call or network access:
```bash
pytest -v
```

---

## Phase 2 (not yet enabled): automated execution via Interactive Brokers

The codebase also contains a full order-execution path (`src/broker/`, `src/orders/`, the `analyze`/`check-confirmations` CLI commands) built for a later phase where the agent proposes or places real orders — it's dormant and unused by `daily-digest`. It targets **Interactive Brokers**, not GBM: GBM has no official trading API, only reverse-engineered community libraries that warn about breaking without notice and possibly violating GBM's Terms of Service. Interactive Brokers offers a free, official, actively-maintained API, accepts Mexican residents, and gives direct access to both the Bolsa Mexicana de Valores (BMV) and US markets.

**Current scope note:** as implemented, this path only trades USD-denominated, SMART-routed US-listed symbols (see `EXCHANGE`/`CURRENCY` in `src/broker/ibkr.py`) — BMV/MXN order routing isn't wired up.

If/when this phase is turned on:

1. **Install and start IB Gateway**, log in with your IBKR **paper-trading** account, and leave it running. This agent never sees your IBKR password — it just connects to the already-authenticated Gateway on `localhost`.
2. Set `TRADING_MODE=paper` (the safe default) and `EXECUTION_MODE=confirm` in `.env`.
3. Run the two-step flow:
   ```bash
   # Analyze a ticker. If the risk manager approves a BUY/SELL, you'll get a
   # Telegram message with an order id.
   python main.py analyze --ticker AAPL

   # Reply on Telegram with /confirm_<id> or /reject_<id>, then run:
   python main.py check-confirmations
   ```
4. Set `EXECUTION_MODE=autonomous` to have risk-approved orders execute immediately instead of waiting for confirmation (still notified after the fact) — only once you trust the confirm-mode behavior.
5. Set `TRADING_MODE=live` (and point IB Gateway at your live account) only when deliberately ready to trade real money; the app refuses to start on a `TRADING_MODE`/port mismatch as a guardrail.
