# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI agent that analyzes stocks (market/fundamental/news data via `yfinance` + an LLM via OpenRouter). Two modes share the same analysis core (`analyze_asset` in `src/agent/financial_agent.py`) but diverge after that:

- **`daily-digest` (current, default mode)**: purely advisory. Analyzes `config.watchlist` once a day and sends one Telegram message with a verdict per ticker (buy/sell/stay put). Never touches a broker. The user executes manually in GBM.
- **`analyze` / `check-confirmations` (dormant "phase 2")**: full order-execution path targeting **Interactive Brokers** (not GBM — GBM has no official API; see README.md "Phase 2"). Built and tested, but not what `daily-digest` uses. Real money is never touched without an explicit `TRADING_MODE=live` change; everything defaults to IBKR's paper account.

When asked to change trading logic, check which mode the change is actually for — `RiskManager.evaluate_signal()` (signal quality only) backs the digest, `RiskManager.evaluate()` (signal quality + allocation/trade-limit) backs execution.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Run the full test suite (pythonpath/testpaths configured in pyproject.toml)
pytest -v

# Run a single test
pytest tests/test_risk_manager.py::test_hold_is_never_approved -v

# Run the current advisory digest (analyzes config.watchlist, sends one Telegram message)
python main.py daily-digest

# Dormant phase-2 execution flow (see Architecture below) — not used by daily-digest
python main.py analyze --ticker AAPL
python main.py check-confirmations
```

`daily-digest` is scheduled via a macOS `launchd` user agent (template at `launchd/com.financialaiagent.dailydigest.plist`, installed to `~/Library/LaunchAgents/`) firing at 7:00 AM local time — not cron. `launchctl list | grep financialaiagent` shows it; logs go to `~/Library/Logs/financial-ai-agent-digest.log`.

There is no lint/format tooling configured in this repo (no ruff/black/mypy config) — don't assume one and invent commands for it.

Most tests (`tests/test_risk_manager.py`, `tests/test_order_store.py`, `tests/test_telegram.py`) are pure/offline and fast. `tests/test_tools.py` makes live calls to `yfinance` and will fail without network access — that's expected, not a regression.

## Architecture

### The core pipeline (`src/pipeline.py`)
`run_daily_digest(config)` is the current entry point: for each ticker in `config.watchlist`, calls `analyze_asset()` then `RiskManager.evaluate_signal()`, formats one line per ticker with the pure, unit-tested `format_digest_line()`, and sends a single digest via `notify_safely`. One ticker's analysis failing (data fetch, LLM error) is caught per-ticker and shown as its own line — it must never abort the rest of the digest.

`run_analysis(ticker, config)` is the dormant phase-2 execution spine, run in this order:
1. `analyze_asset()` (`src/agent/financial_agent.py`) fetches market/fundamental/news data and asks the LLM for a `FinancialRecommendation` (strict Pydantic schema via `PydanticOutputParser`), returned wrapped in an `AnalysisResult` that also carries the raw tool data.
2. `RiskManager.evaluate()` (`src/risk/risk_manager.py`) **re-checks the LLM's output in plain Python** — confidence ≥ threshold, allocation clamped to a hard cap (the schema itself already caps `suggested_allocation_pct` at 5%, but `RiskManager` can enforce an even stricter configured cap), missing/errored tool data blocks the trade, daily trade-count limit. This exists because the LLM's system prompt asking it to follow risk rules is not an enforcement mechanism — treat the LLM's own claims about risk as untrusted, and don't add "trust the model" shortcuts here.
3. If approved, order size (whole shares) is computed from live account equity (`Broker.get_account_equity()`) and current price.
4. The sized order is handed to a `Confirmer` (`src/orders/confirmer.py`) — `HumanConfirmer` (default) creates a row in the SQLite pending-orders store and sends a Telegram alert; `AutonomousConfirmer` executes immediately. Which one runs is selected purely by `EXECUTION_MODE` in `.env` — when adding trading behavior, put it in `RiskManager` or the pipeline, not inside a specific `Confirmer`, so both modes stay in sync.

`run_check_confirmations(config)` is the second half: it polls Telegram for `/confirm_<id>` / `/reject_<id>` replies (`src/notifications/telegram.py`) and, on confirm, actually calls `Broker.place_order()`.

This decision — decide now, confirm/execute later, as two separate CLI subcommands (`main.py`) — is deliberate so `analyze` can run from cron without ever blocking on a human reply.

### Broker abstraction (`src/broker/`)
`Broker` (`base.py`) is a small interface (`connect`, `get_account_equity`, `get_position`, `place_order`); `IBKRBroker` (`ibkr.py`) implements it via `ib_async`, connecting to a **locally-running IB Gateway/TWS that the user already started and logged into**. This codebase never stores or handles IBKR credentials — that's a deliberate security boundary, not an oversight. If asked to add another broker, implement `Broker` rather than special-casing call sites.

Contracts are currently hardcoded to `Stock(ticker, "SMART", "USD")` (`EXCHANGE`/`CURRENCY` constants in `ibkr.py`) — this only trades USD-denominated, SMART-routed US-listed symbols. BMV/MXN access (mentioned in the README as an IBKR-account capability in general) is **not wired up**: adding it means threading an explicit exchange/currency per ticker through `place_order`/`get_position`, not just relaxing the `get_position` symbol match.

`place_order()` only guarantees the order was *sent*; it polls for a terminal fill for up to `timeout_seconds` and gives up without cancelling, since a caller run from cron must never hang. Callers must not assume a returned `OrderResult` means "filled" — use `status_for_fill()` (below).

### Orders store (`src/orders/store.py`)
Plain SQLite (stdlib `sqlite3`, no ORM) tracking order lifecycle: `pending → confirmed → submitted|executed`, or `rejected`/`execution_failed`/`expired`/`stuck_needs_review` along the way. `status_for_fill(broker_status)` is the single place that decides `executed` (broker-confirmed `"Filled"`) vs `submitted` (anything else, e.g. still resting) — always route a fresh `OrderResult` through it rather than assuming a placed order filled. `OrderStore.count_executed_today()` (keyed off `updated_at`, i.e. when the fill was recorded, not when the order was proposed) feeds the `RiskManager`'s daily trade limit — anything that creates orders outside this store will silently break that limit.

`OrderStore.flag_stuck_confirmed()` catches orders where the process died between marking `CONFIRMED` and actually calling the broker; it flags them for manual review rather than retrying, since a blind retry could double-place a trade that already reached IBKR.

### Notifications (`src/notifications/telegram.py`)
Always send via `notify_safely(notifier, text)`, never `notifier.send_message()` directly, outside of `notify_safely`'s own implementation. A Telegram failure (outage, or an unescaped `_`/`*` from LLM-generated text breaking Markdown parsing) must never propagate into the code that just recorded a correct order status — `notify_safely` swallows and logs instead of raising, precisely so a notification failure can't get misread by a surrounding `except` as an execution failure.

### Config (`src/config.py`)
Single `load_config()` entry point reading `.env` into a frozen `Config` dataclass, with validation that fails fast (e.g. refuses to start if `TRADING_MODE=live` is paired with the paper-trading IBKR port). All new tunables should go through this, not scattered `os.getenv()` calls.

### Schema (`src/models/schemas.py`)
`FinancialRecommendation` is the LLM's forced output shape (`PydanticOutputParser` in `financial_agent.py`). Field-level constraints here (e.g. `suggested_allocation_pct: ge=0, le=5`) are the *first* layer of risk enforcement — the `RiskManager` is the second, independent layer. Changing this schema changes what `parser.get_format_instructions()` tells the LLM to produce, so keep field `description`s accurate/instructive.
