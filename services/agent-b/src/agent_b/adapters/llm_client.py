
import os

from langchain_ollama import ChatOllama

MODEL = "qwen2.5:7b" # use qwen2.5:1.5b, if there's not enough memory

def create_llm() -> ChatOllama:
    """Create the local Ollama chat model."""
    model_name = os.getenv("OLLAMA_MODEL", MODEL) 

    return ChatOllama(
        model=model_name,
        temperature=0,
    )
