"""LLM Client wrapper providing a uniform interface for LLM completions and structured outputs."""

import re
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from openai import (
    OpenAI,
    OpenAIError,
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
)
from config.settings import get_settings

T = TypeVar("T", bound=BaseModel)


def clean_code_fence(content: str) -> str:
    """Strip markdown code fence backticks (```python ... ```) if present."""
    if not content:
        return ""
    cleaned = re.sub(r"^```(?:python)?\s*\n", "", content.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip()


class LLMClient:
    """Client interface for invoking OpenAI models with completions and structured outputs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = 30.0,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL
        self.temperature = (
            temperature if temperature is not None else settings.OPENAI_TEMPERATURE
        )
        self.base_url = base_url
        self.timeout = timeout

        self._client: Optional[OpenAI] = None
        if self.is_configured():
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )

    def is_configured(self) -> bool:
        """Check if a valid non-placeholder API key is set."""
        return bool(
            self.api_key
            and self.api_key != "your_openai_api_key_here"
            and not self.api_key.startswith("sk-placeholder")
        )

    def _ensure_client(self) -> OpenAI:
        """Return initialized OpenAI client or raise ValueError if not configured."""
        if not self.is_configured() or self._client is None:
            raise ValueError(
                "OpenAI API key is not configured. "
                "Please add your valid OPENAI_API_KEY in the .env file."
            )
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Generate a text completion from the configured LLM with detailed error handling."""
        client = self._ensure_client()
        temp = temperature if temperature is not None else self.temperature

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temp,
            )
            content = response.choices[0].message.content if response.choices else None
            if not content or not content.strip():
                raise ValueError("OpenAI returned an unexpected empty text completion.")
            return content.strip()

        except AuthenticationError as e:
            raise RuntimeError(
                f"OpenAI Authentication failed: Invalid API key provided. "
                f"Check your OPENAI_API_KEY in .env. Details: {e}"
            ) from e
        except RateLimitError as e:
            raise RuntimeError(
                f"OpenAI Rate limit reached or quota exhausted. "
                f"Check your OpenAI usage limits and billing. Details: {e}"
            ) from e
        except APITimeoutError as e:
            raise RuntimeError(
                f"OpenAI API request timed out after {self.timeout}s. "
                f"Check network latency or increase timeout. Details: {e}"
            ) from e
        except APIConnectionError as e:
            raise RuntimeError(
                f"OpenAI connection error: Network unreachable or proxy failure. Details: {e}"
            ) from e
        except OpenAIError as e:
            raise RuntimeError(f"OpenAI API request failed: {e}") from e

    def generate_structured(
        self,
        prompt: str,
        schema: Optional[Type[T]] = None,
        response_model: Optional[Type[T]] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> T:
        """Generate a structured response parsed directly into a Pydantic model with detailed error handling."""
        target_schema = schema or response_model
        if target_schema is None:
            raise ValueError("Must provide either 'schema' or 'response_model' for structured parsing.")

        client = self._ensure_client()
        temp = temperature if temperature is not None else self.temperature

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=target_schema,
                temperature=temp,
            )
            parsed = response.choices[0].message.parsed if response.choices else None
            if parsed is None:
                raise ValueError("OpenAI returned an empty structured response.")
            return parsed

        except AuthenticationError as e:
            raise RuntimeError(
                f"OpenAI Authentication failed: Invalid API key provided. Details: {e}"
            ) from e
        except RateLimitError as e:
            raise RuntimeError(
                f"OpenAI Rate limit reached or quota exhausted. Details: {e}"
            ) from e
        except APITimeoutError as e:
            raise RuntimeError(
                f"OpenAI API request timed out after {self.timeout}s. Details: {e}"
            ) from e
        except APIConnectionError as e:
            raise RuntimeError(
                f"OpenAI connection error: Network unreachable or proxy failure. Details: {e}"
            ) from e
        except OpenAIError as e:
            raise RuntimeError(f"OpenAI structured parse call failed: {e}") from e

    # Alias for generate_structured
    structured_completion = generate_structured
