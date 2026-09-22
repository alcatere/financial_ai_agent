import requests
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from src.agent.financial_agent import get_llm, llm_timeout_seconds, llm_unreachable_reason
from src.config import load_config

BASE_ENV = {
    "TELEGRAM_BOT_TOKEN": "test-token",
    "TELEGRAM_CHAT_ID": "12345",
}


def _config(monkeypatch, **overrides):
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return load_config()


def test_ollama_provider_builds_chat_ollama(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="ollama", OLLAMA_MODEL="qwen3.5:9b", OLLAMA_BASE_URL="http://localhost:11434")
    llm = get_llm(config)
    assert isinstance(llm, ChatOllama)
    assert llm.model == "qwen3.5:9b"
    assert llm.base_url == "http://localhost:11434"
    assert llm.format == "json"
    assert llm.reasoning is False


def test_openrouter_provider_builds_chat_openai(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="test-key", OPENROUTER_MODEL="anthropic/claude-3.5-sonnet")
    llm = get_llm(config)
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "anthropic/claude-3.5-sonnet"


def test_llm_timeout_is_shorter_than_analysis_timeout(monkeypatch):
    # The client timeout must fire before the per-ticker thread timeout, or
    # it can never cancel anything at the source.
    config = _config(monkeypatch, LLM_PROVIDER="ollama", ANALYSIS_TIMEOUT_SECONDS="180")
    assert llm_timeout_seconds(config) < config.analysis_timeout_seconds
    assert llm_timeout_seconds(config) == 160


def test_llm_timeout_has_a_floor(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="ollama", ANALYSIS_TIMEOUT_SECONDS="10")
    assert llm_timeout_seconds(config) == 30


def test_ollama_client_timeout_uses_derived_value(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="ollama", ANALYSIS_TIMEOUT_SECONDS="100")
    llm = get_llm(config)
    assert llm.client_kwargs["timeout"] == 80


def test_unreachable_check_skipped_for_openrouter(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="k")
    assert llm_unreachable_reason(config) is None


def test_unreachable_check_reports_ollama_down(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="ollama")

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("src.agent.financial_agent.requests.get", refuse)
    reason = llm_unreachable_reason(config)
    assert reason is not None
    assert "not reachable" in reason
    assert "LLM_PROVIDER=openrouter" in reason


def test_unreachable_check_passes_when_ollama_up(monkeypatch):
    config = _config(monkeypatch, LLM_PROVIDER="ollama")

    class OkResponse:
        def raise_for_status(self):
            pass

    monkeypatch.setattr("src.agent.financial_agent.requests.get", lambda *a, **k: OkResponse())
    assert llm_unreachable_reason(config) is None
