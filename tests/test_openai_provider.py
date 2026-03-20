import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from job_hunter.llm.base import get_provider


def _make_mock_openai_module():
    """Create a mock openai module with AsyncOpenAI."""
    mock_module = MagicMock()
    return mock_module


@pytest.fixture(autouse=True)
def mock_openai_module():
    """Ensure 'openai' is mockable even if not installed."""
    mock_module = MagicMock()
    with patch.dict(sys.modules, {"openai": mock_module}):
        yield mock_module


def test_get_provider_returns_openai(mock_openai_module):
    from job_hunter.llm.openai import OpenAIProvider

    provider = get_provider("openai", api_key="test-key", model="gpt-4o-mini")
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.asyncio
async def test_openai_generate_calls_api(mock_openai_module):
    mock_client = AsyncMock()
    mock_openai_module.AsyncOpenAI.return_value = mock_client

    mock_message = MagicMock()
    mock_message.content = "Hello world"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client.chat.completions.create.return_value = mock_response

    from job_hunter.llm.openai import OpenAIProvider

    provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")
    result = await provider.generate("Say hello")

    assert result == "Hello world"
    mock_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_openai_generate_json_mode(mock_openai_module):
    mock_client = AsyncMock()
    mock_openai_module.AsyncOpenAI.return_value = mock_client

    mock_message = MagicMock()
    mock_message.content = '{"score": 8}'
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client.chat.completions.create.return_value = mock_response

    from job_hunter.llm.openai import OpenAIProvider

    provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")
    result = await provider.generate("Score this", json_mode=True)

    assert result == '{"score": 8}'
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_openai_generate_empty_content_returns_empty_string(mock_openai_module):
    mock_client = AsyncMock()
    mock_openai_module.AsyncOpenAI.return_value = mock_client

    mock_message = MagicMock()
    mock_message.content = None
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client.chat.completions.create.return_value = mock_response

    from job_hunter.llm.openai import OpenAIProvider

    provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")
    result = await provider.generate("Say hello")

    assert result == ""
