import asyncio
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod

from .config import config
from .state import LLMProvider

class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def generate_response(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM client is properly configured."""
        pass

class GeminiClient(LLMClient):
    """Google Gemini LLM client."""

    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        self._client = None

    def _get_client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None and self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel('gemini-2.5-pro')
            except ImportError:
                raise ImportError("google-generativeai package is required for Gemini support")
        return self._client

    async def generate_response(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate response using Gemini."""
        client = self._get_client()
        if not client:
            raise ValueError("Gemini client not properly configured")

        # Convert messages to Gemini format
        prompt = self._format_messages_for_gemini(messages)

        try:
            response = client.generate_content(prompt)
            return response.text
        except Exception as e:
            raise Exception(f"Gemini API error: {str(e)}")

    def _format_messages_for_gemini(self, messages: List[Dict[str, str]]) -> str:
        """Format messages for Gemini API."""
        formatted_parts = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                formatted_parts.append(f"System: {content}")
            elif role == "user":
                formatted_parts.append(f"User: {content}")
            elif role == "assistant":
                formatted_parts.append(f"Assistant: {content}")
        return "\n".join(formatted_parts)

    def is_available(self) -> bool:
        """Check if Gemini is available."""
        return bool(self.api_key and self.api_key != "your_gemini_api_key_here")

class OpenAIClient(LLMClient):
    """OpenAI GPT LLM client."""

    def __init__(self):
        self.api_key = config.OPENAI_API_KEY
        self._client = None

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None and self.api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("openai package is required for OpenAI support")
        return self._client

    async def generate_response(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate response using OpenAI."""
        client = self._get_client()
        if not client:
            raise ValueError("OpenAI client not properly configured")

        model = kwargs.get("model", "gpt-4")
        max_tokens = kwargs.get("max_tokens", 1000)
        temperature = kwargs.get("temperature", 0.7)

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}")

    def is_available(self) -> bool:
        """Check if OpenAI is available."""
        return bool(self.api_key and self.api_key != "your_openai_api_key_here")

class AnthropicClient(LLMClient):
    """Anthropic Claude LLM client."""

    def __init__(self):
        self.api_key = config.ANTHROPIC_API_KEY
        self._client = None

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None and self.api_key:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package is required for Claude support")
        return self._client

    async def generate_response(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate response using Claude."""
        client = self._get_client()
        if not client:
            raise ValueError("Anthropic client not properly configured")

        model = kwargs.get("model", "claude-3-sonnet-20240229")
        max_tokens = kwargs.get("max_tokens", 1000)

        # Separate system message from other messages
        system_message = ""
        chat_messages = []

        for message in messages:
            if message.get("role") == "system":
                system_message = message.get("content", "")
            else:
                chat_messages.append(message)

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_message if system_message else None,
                messages=chat_messages
            )
            return response.content[0].text
        except Exception as e:
            raise Exception(f"Anthropic API error: {str(e)}")

    def is_available(self) -> bool:
        """Check if Anthropic is available."""
        return bool(self.api_key and self.api_key != "your_anthropic_api_key_here")

class LLMRouter:
    """Router for managing multiple LLM providers."""

    def __init__(self):
        self.clients = {
            LLMProvider.GEMINI: GeminiClient(),
            LLMProvider.OPENAI: OpenAIClient(),
            LLMProvider.ANTHROPIC: AnthropicClient(),
        }

    def get_client(self, provider: LLMProvider) -> LLMClient:
        """Get LLM client for the specified provider."""
        if provider not in self.clients:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        client = self.clients[provider]
        if not client.is_available():
            raise ValueError(f"LLM provider {provider} is not properly configured")

        return client

    def get_available_providers(self) -> List[LLMProvider]:
        """Get list of available LLM providers."""
        available = []
        for provider, client in self.clients.items():
            if client.is_available():
                available.append(provider)
        return available

    def get_default_provider(self) -> LLMProvider:
        """Get the default LLM provider."""
        default = LLMProvider(config.DEFAULT_LLM_PROVIDER)
        if default in self.get_available_providers():
            return default

        # Fallback to first available provider
        available = self.get_available_providers()
        if available:
            return available[0]

        raise ValueError("No LLM providers are properly configured")

    async def generate_response(
        self, 
        provider: LLMProvider, 
        messages: List[Dict[str, str]], 
        **kwargs
    ) -> str:
        """Generate response using the specified provider."""
        client = self.get_client(provider)
        return await client.generate_response(messages, **kwargs)

    async def generate_with_fallback(
        self, 
        messages: List[Dict[str, str]], 
        preferred_provider: Optional[LLMProvider] = None,
        **kwargs
    ) -> tuple[str, LLMProvider]:
        """Generate response with fallback to other providers if needed."""
        providers_to_try = []

        # Try preferred provider first
        if preferred_provider and preferred_provider in self.get_available_providers():
            providers_to_try.append(preferred_provider)

        # Add other available providers as fallbacks
        for provider in self.get_available_providers():
            if provider not in providers_to_try:
                providers_to_try.append(provider)

        last_error = None
        for provider in providers_to_try:
            try:
                response = await self.generate_response(provider, messages, **kwargs)
                return response, provider
            except Exception as e:
                last_error = e
                continue

        raise Exception(f"All LLM providers failed. Last error: {last_error}")

# Global LLM router instance
llm_router = LLMRouter()
