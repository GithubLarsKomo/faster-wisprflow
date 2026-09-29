"""Central provider contracts for transcription and LLM backends.

The UI may keep legacy display labels for compatibility, but runtime routing and
fixed public endpoints must come from this module rather than independent
string literals spread across the application.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    display_name: str
    requires_token: bool
    chat_url: str | None = None
    transcription_url: str | None = None
    models_url: str | None = None
    transcription_models_url: str | None = None
    auth_style: str = "bearer"


_PROVIDERS = {
    "local": ProviderDefinition(
        id="local",
        display_name="local",
        requires_token=False,
    ),
    "ollama": ProviderDefinition(
        id="ollama",
        display_name="Ollama",
        requires_token=False,
    ),
    "lm_studio": ProviderDefinition(
        id="lm_studio",
        display_name="LM Studio",
        requires_token=False,
    ),
    "groq": ProviderDefinition(
        id="groq",
        display_name="Groq",
        requires_token=True,
        chat_url="https://api.groq.com/openai/v1/chat/completions",
        transcription_url="https://api.groq.com/openai/v1/audio/transcriptions",
        models_url="https://api.groq.com/openai/v1/models",
        transcription_models_url="https://api.groq.com/openai/v1/models",
    ),
    "openrouter": ProviderDefinition(
        id="openrouter",
        display_name="Openrouter",
        requires_token=True,
        chat_url="https://openrouter.ai/api/v1/chat/completions",
        transcription_url="https://openrouter.ai/api/v1/audio/transcriptions",
        models_url="https://openrouter.ai/api/v1/models",
        transcription_models_url=(
            "https://openrouter.ai/api/v1/models?output_modalities=transcription"
        ),
    ),
    "openai": ProviderDefinition(
        id="openai",
        display_name="OpenAI",
        requires_token=True,
        chat_url="https://api.openai.com/v1/chat/completions",
        transcription_url="https://api.openai.com/v1/audio/transcriptions",
        models_url="https://api.openai.com/v1/models",
        transcription_models_url="https://api.openai.com/v1/models",
    ),
    "anthropic": ProviderDefinition(
        id="anthropic",
        display_name="Anthropic",
        requires_token=True,
        chat_url="https://api.anthropic.com/v1/messages",
        models_url="https://api.anthropic.com/v1/models",
        auth_style="anthropic",
    ),
    # Azure OpenAI requires an instance-specific endpoint, so no fixed public
    # endpoint is stored here. It intentionally remains URL-configurable.
    "azure_openai": ProviderDefinition(
        id="azure_openai",
        display_name="Azure OpenAI",
        requires_token=True,
    ),
}

_ALIASES = {
    "local": "local",
    "lokal": "local",
    "ollama": "ollama",
    "lm studio": "lm_studio",
    "lm_studio": "lm_studio",
    "groq": "groq",
    "openrouter": "openrouter",
    "open router": "openrouter",
    "openai": "openai",
    "open ai": "openai",
    "anthropic": "anthropic",
    "azure openai": "azure_openai",
    "azure_openai": "azure_openai",
}

_LLM_IDS = (
    "ollama",
    "lm_studio",
    "groq",
    "openrouter",
    "openai",
    "anthropic",
    "azure_openai",
)

_TRANSCRIPTION_IDS = (
    "local",
    "groq",
    "openrouter",
    "openai",
)


def normalize_provider(value: str | None) -> str:
    """Return a stable provider ID while accepting legacy persisted labels."""
    raw = (value or "").strip()
    if not raw:
        return ""
    return _ALIASES.get(raw.lower(), raw.lower().replace(" ", "_"))


def get_provider(value: str | None) -> ProviderDefinition | None:
    return _PROVIDERS.get(normalize_provider(value))


def llm_provider_labels() -> list[str]:
    return [_PROVIDERS[provider_id].display_name for provider_id in _LLM_IDS]


def transcription_provider_labels() -> list[str]:
    return [_PROVIDERS[provider_id].display_name for provider_id in _TRANSCRIPTION_IDS]
