import os
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

from app.observability import log_event

SUPPORTED_LLM_PROVIDERS = {"openai", "openrouter", "gemini", "ollama"}
DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-oss-120b:free",
    "gemini": "gemini-flash-latest",
    "ollama": "llama3",
}
MODEL_ENV_BY_PROVIDER = {
    "openai": "OPENAI_MODEL",
    "openrouter": "OPENROUTER_MODEL",
    "gemini": "GOOGLE_MODEL",
    "ollama": "OLLAMA_MODEL",
}
API_KEY_ENV_BY_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


class LLMConfigurationError(RuntimeError):
    pass


def resolve_llm_config(model_type: Optional[str] = None, model_name: Optional[str] = None) -> tuple[str, str]:
    provider = (model_type or os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
        raise ValueError(f"Unsupported LLM provider '{provider}'. Supported providers: {supported}.")

    provider_model_env = MODEL_ENV_BY_PROVIDER[provider]
    provider_model = os.getenv(provider_model_env, "").strip()
    default_model = DEFAULT_MODEL_BY_PROVIDER[provider]
    model = (model_name or provider_model or os.getenv("LLM_MODEL", "").strip() or default_model).strip()
    return provider, model


def validate_llm_config(model_type: Optional[str] = None, model_name: Optional[str] = None) -> tuple[str, str]:
    provider, name = resolve_llm_config(model_type, model_name)
    key_env = API_KEY_ENV_BY_PROVIDER.get(provider)
    if key_env and not os.getenv(key_env, "").strip():
        log_event("llm.provider_key_missing", level="warning", provider=provider, key_name=key_env)
        raise LLMConfigurationError(
            f"LLM provider {provider} is missing {key_env}. Add it to your local .env and restart Docker Compose before starting matching."
        )
    return provider, name


def get_llm(model_type: Optional[str] = None, model_name: Optional[str] = None):
    """
    Factory to return an LLM instance.
    model_type can be "openai", "openrouter", "gemini", or "ollama".
    When omitted, LLM_PROVIDER and model env vars choose the deployment default.
    """
    provider, name = validate_llm_config(model_type, model_name)

    if provider == "ollama":
        return ChatOllama(model=name)
    elif provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        return ChatGoogleGenerativeAI(model=name, google_api_key=api_key, temperature=0, convert_system_message_to_human=True)
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        return ChatOpenAI(
            model=name, 
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            model_kwargs={"extra_body": {"reasoning": {"enabled": True}}},
            default_headers={
                "HTTP-Referer": os.getenv("FRONTEND_URL", "http://localhost:5173"),
                "X-Title": "JobMatchHero Matching Workflow"
            }
        )
    else:
        return ChatOpenAI(model=name, temperature=0)
