import pytest

from app.agent.llm_factory import resolve_llm_config


LLM_ENV_KEYS = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OPENAI_MODEL",
    "OPENROUTER_MODEL",
    "GOOGLE_MODEL",
    "OLLAMA_MODEL",
)


@pytest.fixture(autouse=True)
def clear_llm_env(monkeypatch):
    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_llm_config_defaults_to_openai():
    assert resolve_llm_config() == ("openai", "gpt-4o")


def test_resolve_llm_config_uses_deployment_provider_and_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")

    assert resolve_llm_config() == ("openrouter", "anthropic/claude-3.5-sonnet")


def test_resolve_llm_config_allows_call_level_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_MODEL", "gemini-1.5-pro")

    assert resolve_llm_config(model_type="ollama", model_name="llama3.1") == ("ollama", "llama3.1")


def test_resolve_llm_config_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        resolve_llm_config()
