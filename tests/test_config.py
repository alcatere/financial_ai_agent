import pytest
from src.config import DEFAULT_WATCHLIST, load_config

REQUIRED_ENV = {
    "OPENROUTER_API_KEY": "test-key",
    "TELEGRAM_BOT_TOKEN": "test-token",
    "TELEGRAM_CHAT_ID": "12345",
}


def set_env(monkeypatch, **overrides):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


def test_defaults_to_safe_paper_mode(monkeypatch):
    set_env(monkeypatch)
    config = load_config()
    assert config.trading_mode == "paper"
    assert config.ibkr_port == 4002
    assert config.execution_mode == "confirm"


def test_live_mode_uses_live_port_by_default(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="live")
    config = load_config()
    assert config.ibkr_port == 4001


def test_rejects_live_mode_with_paper_port(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="live", IBKR_PORT="4002")
    with pytest.raises(ValueError, match="paper-trading port"):
        load_config()


def test_rejects_paper_mode_with_live_port(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="paper", IBKR_PORT="4001")
    with pytest.raises(ValueError, match="live-trading port"):
        load_config()


def test_confirmations_client_id_defaults_to_client_id_plus_one(monkeypatch):
    set_env(monkeypatch, IBKR_CLIENT_ID="5")
    config = load_config()
    assert config.ibkr_client_id == 5
    assert config.ibkr_client_id_confirmations == 6


def test_openrouter_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_config()


def test_ollama_provider_does_not_require_openrouter_key(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config = load_config()
    assert config.llm_provider == "ollama"


def test_llm_provider_defaults_to_ollama(monkeypatch):
    set_env(monkeypatch)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    config = load_config()
    assert config.llm_provider == "ollama"


def test_invalid_llm_provider_raises(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="gpt4all")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_config()


def test_ollama_defaults(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("ANALYSIS_TIMEOUT_SECONDS", raising=False)
    config = load_config()
    assert config.ollama_model == "qwen3.5:9b"
    assert config.ollama_base_url == "http://localhost:11434"
    assert config.analysis_timeout_seconds == 180


def test_analysis_timeout_is_configurable(monkeypatch):
    set_env(monkeypatch, ANALYSIS_TIMEOUT_SECONDS="45")
    config = load_config()
    assert config.analysis_timeout_seconds == 45


def test_missing_telegram_config_raises(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM"):
        load_config()


def test_watchlist_defaults_when_unset(monkeypatch):
    set_env(monkeypatch)
    monkeypatch.delenv("WATCHLIST", raising=False)
    config = load_config()
    assert config.watchlist == DEFAULT_WATCHLIST


def test_watchlist_parses_comma_separated_list(monkeypatch):
    set_env(monkeypatch, WATCHLIST="aapl, msft , walmex.mx")
    config = load_config()
    assert config.watchlist == ["AAPL", "MSFT", "WALMEX.MX"]


def test_watchlist_ignores_empty_entries(monkeypatch):
    set_env(monkeypatch, WATCHLIST="aapl,,msft,")
    config = load_config()
    assert config.watchlist == ["AAPL", "MSFT"]


def test_watchlist_whitespace_only_falls_back_to_default(monkeypatch):
    set_env(monkeypatch, WATCHLIST="   ")
    config = load_config()
    assert config.watchlist == DEFAULT_WATCHLIST
