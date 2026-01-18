import os
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

def get_llm(model_type: str = "openai", model_name: str = None):
    """
    Factory to return an LLM instance.
    model_type: "openai" or "ollama"
    """
    if model_type == "ollama":
        name = model_name or "llama3" # Default to llama3 for Ollama
        return ChatOllama(model=name)
    elif model_type == "openrouter":
        name = model_name or "openai/gpt-oss-120b:free"
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print("Warning: OPENROUTER_API_KEY not found.")
        return ChatOpenAI(
            model=name, 
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            model_kwargs={"extra_body": {"reasoning": {"enabled": True}}},
            default_headers={
                "HTTP-Referer": "http://localhost:5173",
                "X-Title": "J Hunter Agent"
            }
        )
    else:
        # Default to OpenAI
        name = model_name or "gpt-4o"
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
             # Fallback or error - for now log a warning? 
             # Or maybe just return it and let it fail if used?
             pass
        return ChatOpenAI(model=name, temperature=0)
