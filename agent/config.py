import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class for the autonomous agent."""

    # API Keys
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")

    # MCP Server Configuration
    MCP_SERVER_MODE: str = os.getenv("MCP_SERVER_MODE", "http")  # "http" or "stdio"
    MCP_SERVER_BASE_URL: str = os.getenv("MCP_SERVER_BASE_URL", "http://127.0.0.1:8080")
    MCP_SERVER_URL: str = f"{MCP_SERVER_BASE_URL}/mcp/message"
    MCP_TOOLS_URL: str = f"{MCP_SERVER_BASE_URL}/mcp/tools"
    MCP_SERVER_COMMAND: str = os.getenv("MCP_SERVER_COMMAND", "java -jar target/book-service-1.0.0.jar --mcp")

    # LLM Configuration
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "gemini")
    SUPPORTED_LLM_PROVIDERS = ["gemini", "openai", "anthropic"]

    # Web App Configuration
    FLASK_ENV: str = os.getenv("FLASK_ENV", "development")
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    FLASK_HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))

    # Agent Configuration
    MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "10"))
    TOOL_TIMEOUT: int = int(os.getenv("TOOL_TIMEOUT", "30"))

    @classmethod
    def validate_api_keys(cls) -> dict[str, bool]:
        """Validate that required API keys are present."""
        return {
            "gemini": bool(cls.GEMINI_API_KEY and cls.GEMINI_API_KEY != "your_gemini_api_key_here"),
            "openai": bool(cls.OPENAI_API_KEY and cls.OPENAI_API_KEY != "your_openai_api_key_here"),
            "anthropic": bool(cls.ANTHROPIC_API_KEY and cls.ANTHROPIC_API_KEY != "your_anthropic_api_key_here"),
        }

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of LLM providers with valid API keys."""
        validation = cls.validate_api_keys()
        return [provider for provider, is_valid in validation.items() if is_valid]

    @classmethod
    def is_provider_available(cls, provider: str) -> bool:
        """Check if a specific LLM provider is available."""
        return provider in cls.get_available_providers()

# Global config instance
config = Config()
