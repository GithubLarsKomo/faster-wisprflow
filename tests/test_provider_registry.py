"""Contract tests for the central provider registry."""

from provider_registry import (
    get_provider,
    llm_provider_labels,
    normalize_provider,
    transcription_provider_labels,
)


def test_legacy_labels_normalize_to_stable_ids():
    assert normalize_provider("Openrouter") == "openrouter"
    assert normalize_provider("LM Studio") == "lm_studio"
    assert normalize_provider("Azure OpenAI") == "azure_openai"
    assert normalize_provider("lokal") == "local"


def test_groq_contract_uses_openai_compatible_base_path():
    provider = get_provider("Groq")
    assert provider is not None
    assert provider.chat_url == "https://api.groq.com/openai/v1/chat/completions"
    assert (
        provider.transcription_url
        == "https://api.groq.com/openai/v1/audio/transcriptions"
    )
    assert provider.models_url == "https://api.groq.com/openai/v1/models"


def test_openrouter_transcription_contract_uses_filtered_model_catalog():
    provider = get_provider("Openrouter")
    assert provider is not None
    assert (
        provider.transcription_url
        == "https://openrouter.ai/api/v1/audio/transcriptions"
    )
    assert provider.transcription_models_url.endswith(
        "?output_modalities=transcription"
    )


def test_supported_provider_labels_are_generated_from_registry():
    assert transcription_provider_labels() == [
        "local",
        "Groq",
        "Openrouter",
        "OpenAI",
    ]
    assert llm_provider_labels() == [
        "Ollama",
        "LM Studio",
        "Groq",
        "Openrouter",
        "OpenAI",
        "Anthropic",
        "Azure OpenAI",
    ]
