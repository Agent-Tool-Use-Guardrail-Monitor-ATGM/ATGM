
import os

from langchain_ollama import ChatOllama


def create_llm() -> ChatOllama:
    """Create the local Ollama chat model."""
    model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:7b") # qwen2.5:1.5b, if there's not enough memory for 7b, qwen2.5:7b

    return ChatOllama(
        model=model_name,
        temperature=0,
    )
