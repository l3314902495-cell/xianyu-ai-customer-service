import pytest
from fastapi import HTTPException

from app.api.ai import provider_for, validate_provider
from app.schemas import ProviderUpdate
from app.services.llm import MockLLMProvider, OpenAICompatibleProvider


def provider_body(**changes) -> ProviderUpdate:
    values = {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1/",
        "api_key": "",
        "model_name": "test-model",
        "temperature": 0.2,
        "max_tokens": 800,
        "timeout": 30,
    }
    values.update(changes)
    return ProviderUpdate(**values)


def test_provider_validation_normalizes_url_and_reuses_saved_key():
    name, url = validate_provider(provider_body(), existing_key="saved-secret")
    assert name == "openai"
    assert url == "https://api.openai.com/v1"

    provider = provider_for(provider_body(), existing_key="saved-secret")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.api_key == "saved-secret"
    assert provider.name == "openai"
    assert provider.chat_completions_url == "https://api.openai.com/v1/chat/completions"


def test_provider_validation_rejects_invalid_url_and_missing_key():
    with pytest.raises(HTTPException, match="HTTP"):
        validate_provider(provider_body(base_url="file:///tmp/model", api_key="secret"))
    with pytest.raises(HTTPException, match="API Key"):
        validate_provider(provider_body())
    with pytest.raises(HTTPException, match="API Key"):
        validate_provider(provider_body(clear_api_key=True), existing_key="saved-secret")


def test_mock_provider_needs_no_remote_credentials():
    provider = provider_for(
        provider_body(provider="mock", base_url="", model_name="mock-v1")
    )
    assert isinstance(provider, MockLLMProvider)
