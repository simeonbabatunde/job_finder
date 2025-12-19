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
    else:
        # Default to OpenAI
        name = model_name or "gpt-4o"
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
             # Fallback or error - for now log a warning? 
             # Or maybe just return it and let it fail if used?
             pass
        return ChatOpenAI(model=name, temperature=0)
