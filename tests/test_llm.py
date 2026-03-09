import pytest
from unittest.mock import MagicMock, patch
from job_hunter.llm.base import get_provider
from job_hunter.llm.gemini import GeminiProvider


def test_get_provider_returns_gemini():
    with patch("job_hunter.llm.gemini.genai"):
        provider = get_provider("gemini", api_key="test", model="gemini-2.5-flash")
        assert isinstance(provider, GeminiProvider)


def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("gpt-local", api_key="test", model="test")


@pytest.mark.asyncio
async def test_gemini_generate_calls_api():
    with patch("job_hunter.llm.gemini.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"score": 8}'
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
        result = await provider.generate("Score this job", json_mode=True)

        assert result == '{"score": 8}'
        mock_client.models.generate_content.assert_called_once()
