"""Unit tests for the LLMClient module with comprehensive error handling."""

from unittest.mock import MagicMock, patch
import pytest
from pydantic import BaseModel
from openai import (
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
)
from core.llm_client import LLMClient, clean_code_fence


class SampleOutputSchema(BaseModel):
    message: str
    count: int


def test_clean_code_fence():
    """Verify markdown code fence stripping."""
    raw_code = "```python\ndef test_api():\n    assert True\n```"
    assert clean_code_fence(raw_code) == "def test_api():\n    assert True"

    raw_generic = "```\ndef test_generic():\n    pass\n```"
    assert clean_code_fence(raw_generic) == "def test_generic():\n    pass"

    clean_plain = "def test_plain():\n    pass"
    assert clean_code_fence(clean_plain) == clean_plain


def test_llm_client_unconfigured_raises_error():
    """Verify unconfigured client raises descriptive ValueError upon generation."""
    client = LLMClient(api_key="")
    assert not client.is_configured()

    with pytest.raises(ValueError, match="OpenAI API key is not configured"):
        client.generate("Generate test")


def test_llm_client_mock_generate():
    """Verify text completion invocation via mocked OpenAI SDK."""
    mock_choice = MagicMock()
    mock_choice.message.content = "import pytest\ndef test_sample(): pass"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("core.llm_client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_response
        mock_openai_cls.return_value = mock_instance

        client = LLMClient(api_key="sk-test-mock-key")
        assert client.is_configured()

        output = client.generate("Hello", system_prompt="You are an assistant")
        assert "def test_sample" in output
        mock_instance.chat.completions.create.assert_called_once()


def test_llm_client_handles_authentication_error():
    """Verify client wraps AuthenticationError with actionable guidance."""
    with patch("core.llm_client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.side_effect = AuthenticationError(
            message="Incorrect API key",
            response=MagicMock(),
            body=None,
        )
        mock_openai_cls.return_value = mock_instance

        client = LLMClient(api_key="sk-invalid-key")
        with pytest.raises(RuntimeError, match="OpenAI Authentication failed"):
            client.generate("Test prompt")


def test_llm_client_handles_rate_limit_error():
    """Verify client wraps RateLimitError with quota/billing message."""
    with patch("core.llm_client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.side_effect = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(),
            body=None,
        )
        mock_openai_cls.return_value = mock_instance

        client = LLMClient(api_key="sk-test-key")
        with pytest.raises(RuntimeError, match="Rate limit reached or quota exhausted"):
            client.generate("Test prompt")


def test_llm_client_handles_timeout_and_connection_errors():
    """Verify client wraps network timeouts and connection errors."""
    with patch("core.llm_client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
        mock_openai_cls.return_value = mock_instance

        client = LLMClient(api_key="sk-test-key")
        with pytest.raises(RuntimeError, match="request timed out"):
            client.generate("Test prompt")


def test_llm_client_handles_empty_response():
    """Verify client raises ValueError if OpenAI returns an empty response."""
    mock_choice = MagicMock()
    mock_choice.message.content = "   "
    mock_response = MagicMock(choices=[mock_choice])

    with patch("core.llm_client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_response
        mock_openai_cls.return_value = mock_instance

        client = LLMClient(api_key="sk-test-key")
        with pytest.raises(ValueError, match="unexpected empty text completion"):
            client.generate("Test prompt")


def test_llm_client_mock_structured():
    """Verify structured output parsing via mocked OpenAI SDK."""
    expected_data = SampleOutputSchema(message="hello world", count=42)

    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(parsed=expected_data))]

    with patch("core.llm_client.OpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.beta.chat.completions.parse.return_value = mock_completion
        mock_openai_cls.return_value = mock_instance

        client = LLMClient(api_key="sk-test-mock-key")
        result = client.generate_structured("Get data", schema=SampleOutputSchema)

        assert isinstance(result, SampleOutputSchema)
        assert result.message == "hello world"
        assert result.count == 42
