import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()

PAPER_PORT = 4002
LIVE_PORT = 4001
DEFAULT_WATCHLIST = ["AAPL", "MSFT", "WALMEX.MX", "GFNORTEO.MX", "AMXL.MX"]


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    openrouter_model: str
    trading_mode: str
    execution_mode: str
    ibkr_host: str
    ibkr_port: int
    ibkr_client_id: int
    ibkr_client_id_confirmations: int
    max_allocation_pct: float
    min_confidence: int
    max_daily_trades: int
    pending_order_ttl_minutes: int
    telegram_bot_token: str
    telegram_chat_id: str
    orders_db_path: str
    watchlist: List[str]

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"

    @property
    def mode_label(self) -> str:
        return "LIVE" if self.is_live else "PAPER"


def load_config() -> Config:
    trading_mode = os.getenv("TRADING_MODE", "paper").lower()
    if trading_mode not in ("paper", "live"):
        raise ValueError("TRADING_MODE must be 'paper' or 'live'")

    execution_mode = os.getenv("EXECUTION_MODE", "confirm").lower()
    if execution_mode not in ("confirm", "autonomous"):
        raise ValueError("EXECUTION_MODE must be 'confirm' or 'autonomous'")

    default_port = LIVE_PORT if trading_mode == "live" else PAPER_PORT
    client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))

    watchlist_raw = os.getenv("WATCHLIST", "")
    parsed_watchlist = [t.strip().upper() for t in watchlist_raw.split(",") if t.strip()]
    # Falls back to the default for both an unset WATCHLIST and one that's
    # present but empty/whitespace-only after parsing - either way there's
    # nothing to scan, so silently running with zero tickers would be worse.
    watchlist = parsed_watchlist if parsed_watchlist else list(DEFAULT_WATCHLIST)

    config = Config(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
        trading_mode=trading_mode,
        execution_mode=execution_mode,
        ibkr_host=os.getenv("IBKR_HOST", "127.0.0.1"),
        ibkr_port=int(os.getenv("IBKR_PORT", default_port)),
        ibkr_client_id=client_id,
        ibkr_client_id_confirmations=int(
            os.getenv("IBKR_CLIENT_ID_CONFIRMATIONS", str(client_id + 1))
        ),
        max_allocation_pct=float(os.getenv("MAX_ALLOCATION_PCT", "5")),
        min_confidence=int(os.getenv("MIN_CONFIDENCE", "70")),
        max_daily_trades=int(os.getenv("MAX_DAILY_TRADES", "3")),
        pending_order_ttl_minutes=int(os.getenv("PENDING_ORDER_TTL_MINUTES", "120")),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        orders_db_path=os.getenv("ORDERS_DB_PATH", "data/orders.db"),
        watchlist=watchlist,
    )

    if not config.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable not set")
    if not (config.telegram_bot_token and config.telegram_chat_id):
        raise ValueError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set: the agent reports "
            "every proposal and execution over Telegram"
        )
    if config.is_live and config.ibkr_port == PAPER_PORT:
        raise ValueError(
            f"TRADING_MODE=live but IBKR_PORT={PAPER_PORT} is the paper-trading port. "
            "Refusing to start with a contradictory configuration."
        )
    if not config.is_live and config.ibkr_port == LIVE_PORT:
        raise ValueError(
            f"TRADING_MODE=paper but IBKR_PORT={LIVE_PORT} is the live-trading port. "
            "Refusing to start with a contradictory configuration."
        )

    return config
