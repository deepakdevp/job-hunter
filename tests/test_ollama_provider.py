import pytest
from unittest.mock import AsyncMock, patch

import httpx

from job_hunter.llm.base import get_provider
from job_hunter.llm.ollama import OllamaProvider


def test_get_provider_returns_ollama():
    provider = get_provider("ollama", api_key="ignored", model="llama3.1")
    assert isinstance(provider, OllamaProvider)


def test_ollama_default_host():
    provider = OllamaProvider(model="llama3.1")
    assert provider._host == "http://localhost:11434"


def test_ollama_custom_host():
    provider = OllamaProvider(model="llama3.1", host="http://myhost:11434/")
    assert provider._host == "http://myhost:11434"


def test_ollama_host_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://envhost:11434")
    provider = OllamaProvider(model="llama3.1")
    assert provider._host == "http://envhost:11434"


@pytest.mark.asyncio
async def test_ollama_generate_calls_api():
    provider = OllamaProvider(model="llama3.1")

    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "Hello world"}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        result = await provider.generate("Say hello")

    assert result == "Hello world"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["model"] == "llama3.1"
    assert call_kwargs[1]["json"]["stream"] is False


@pytest.mark.asyncio
async def test_ollama_generate_json_mode():
    provider = OllamaProvider(model="llama3.1")

    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": '{"score": 8}'}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        result = await provider.generate("Score this", json_mode=True)

    assert result == '{"score": 8}'
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["format"] == "json"


@pytest.mark.asyncio
async def test_ollama_generate_missing_response_key():
    provider = OllamaProvider(model="llama3.1")

    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        result = await provider.generate("Say hello")

    assert result == ""
