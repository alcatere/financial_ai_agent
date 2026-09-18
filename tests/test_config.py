import pytest
from src.config import load_config

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


def test_missing_openrouter_key_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_config()


def test_missing_telegram_config_raises(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValueError, match="TELEGRAM"):
        load_config()
