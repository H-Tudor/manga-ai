from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel


def create_llm(backend: str | None = None) -> BaseChatModel:
    """Return a vision-capable chat model for the requested backend.

    The backend is resolved in this order:
    1. The *backend* argument passed to this function.
    2. The ``AI_BACKEND`` environment variable.
    3. Defaults to ``"openai"``.

    Supported backend strings: ``"openai"``, ``"anthropic"``, ``"ollama"``.

    Model names are configurable via environment variables:
    - ``OPENAI_MODEL``   (default: ``gpt-4o``)
    - ``ANTHROPIC_MODEL`` (default: ``claude-3-5-sonnet-20241022``)
    - ``OLLAMA_MODEL``   (default: ``minicpm-v``)
    - ``OLLAMA_BASE_URL`` (default: ``http://localhost:11434``)
    """
    resolved = (backend or os.getenv("AI_BACKEND", "openai")).lower().strip()

    if resolved == "openai":
        from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            temperature=0,
        )

    if resolved == "anthropic":
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-untyped]

        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            temperature=0,
        )

    if resolved == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore[import-untyped]

        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "minicpm-v"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
            format="json",
        )

    raise ValueError(
        f"Unknown AI backend '{resolved}'. "
        "Valid options: 'openai', 'anthropic', 'ollama'."
    )
