"""
Structured error hierarchy for Amalgam.
Every error carries:
- service: dot-notation service identifier (e.g. "voice.tts.edge-tts")
- severity: human-readable severity level
- recoverable: bool — can the user fix this (start a service, check API key)?
- suggestion: user-visible actionable text
- details: optional machine-parseable dict

Usage:
    raise TTSError("Edge TTS synthesis failed",
                   service="voice.tts.edge-tts",
                   recoverable=True,
                   suggestion="Check that edge-tts is installed: pip install edge-tts",
                   details={"status_code": 500})

    # In a handler:
    except ServiceError as e:
        send_ws({"type": "error", **e.to_dict()})
"""

from __future__ import annotations
from typing import Any, Optional


class ServiceError(Exception):
    """
    Base class for all service-level errors.

    Attributes:
        service: Dot-notation service identifier (e.g. "llm.provider.gemini")
        message: Human-readable error description
        recoverable: True if user can fix (check API key, start service)
        suggestion: Actionable text for the user
        details: Optional machine-parseable extra info
    """

    def __init__(
        self,
        message: str,
        service: str = "unknown",
        recoverable: bool = False,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        self.service = service
        self.recoverable = recoverable
        self.suggestion = suggestion
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        """Serialize to dict for WebSocket/frontend consumption."""
        return {
            "type": "error",
            "service": self.service,
            "message": str(self),
            "recoverable": self.recoverable,
            "suggestion": self.suggestion,
            "details": self.details,
        }

    def __str__(self) -> str:
        return f"[{self.service}] {super().__str__()}"


class LLMError(ServiceError):
    """LLM provider errors (auth, timeout, rate limit, etc.)."""

    def __init__(
        self,
        message: str,
        service: str = "llm.provider.unknown",
        recoverable: bool = True,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        super().__init__(message, service, recoverable, suggestion, details)


class ProviderAuthError(LLMError):
    """API key invalid or missing."""

    def __init__(
        self,
        provider: str = "unknown",
        service: str = "",
        details: Optional[dict] = None,
    ):
        service = service or f"llm.provider.{provider}"
        suggestion = f"Check your {provider} API key in Settings → Provider → {provider}"
        super().__init__(
            f"{provider}: API key is invalid or missing",
            service=service,
            recoverable=True,
            suggestion=suggestion,
            details=details,
        )


class ProviderTimeoutError(LLMError):
    """Provider timed out."""

    def __init__(
        self,
        provider: str = "unknown",
        timeout: int = 30,
        service: str = "",
    ):
        service = service or f"llm.provider.{provider}"
        super().__init__(
            f"{provider}: request timed out after {timeout}s",
            service=service,
            recoverable=True,
            suggestion=f"Check your network connection or increase timeout in Advanced settings",
            details={"timeout": timeout},
        )


class ProviderRateLimitError(LLMError):
    """Rate limited by provider."""

    def __init__(self, provider: str = "unknown", retry_after: int = 0, service: str = ""):
        service = service or f"llm.provider.{provider}"
        msg = f"{provider}: rate limited"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        super().__init__(
            msg,
            service=service,
            recoverable=True,
            suggestion="Wait before sending another request, or switch to a different provider",
            details={"retry_after": retry_after},
        )


class TTSError(ServiceError):
    """TTS engine errors (synthesis failure, model not found, etc.)."""

    def __init__(
        self,
        message: str,
        service: str = "voice.tts.unknown",
        recoverable: bool = True,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        super().__init__(message, service, recoverable, suggestion, details)


class TTSModelNotFoundError(TTSError):
    """TTS model file not found."""

    def __init__(self, engine: str = "unknown", model: str = "", service: str = ""):
        service = service or f"voice.tts.{engine}"
        super().__init__(
            f"{engine}: model not found ({model})",
            service=service,
            recoverable=True,
            suggestion=f"Install the {model} model or switch to a different TTS engine",
            details={"engine": engine, "model": model},
        )


class TTSConnectionError(TTSError):
    """Cannot connect to TTS service."""

    def __init__(self, engine: str = "unknown", url: str = "", service: str = ""):
        service = service or f"voice.tts.{engine}"
        super().__init__(
            f"{engine}: cannot connect to {url}",
            service=service,
            recoverable=True,
            suggestion=f"Make sure {engine} is running at {url}",
            details={"engine": engine, "url": url},
        )


class STTError(ServiceError):
    """STT engine errors."""

    def __init__(
        self,
        message: str,
        service: str = "voice.stt.unknown",
        recoverable: bool = True,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        super().__init__(message, service, recoverable, suggestion, details)


class STTModelNotFoundError(STTError):
    """STT model file not found."""

    def __init__(self, engine: str = "unknown", model: str = "", service: str = ""):
        service = service or f"voice.stt.{engine}"
        super().__init__(
            f"{engine}: model not found ({model})",
            service=service,
            recoverable=True,
            suggestion=f"Install the {model} model: python -m faster_whisper.download {model}",
            details={"engine": engine, "model": model},
        )


class STTConnectionError(STTError):
    """Cannot connect to STT service."""

    def __init__(self, engine: str = "unknown", url: str = "", service: str = ""):
        service = service or f"voice.stt.{engine}"
        super().__init__(
            f"{engine}: cannot connect to {url}",
            service=service,
            recoverable=True,
            suggestion=f"Make sure {engine} is running at {url}",
            details={"engine": engine, "url": url},
        )


class MCPServerError(ServiceError):
    """MCP server errors."""

    def __init__(
        self,
        message: str,
        server: str = "unknown",
        recoverable: bool = True,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        service = f"mcp.server.{server}"
        super().__init__(message, service, recoverable, suggestion, details)


class MemoryError(ServiceError):
    """Memory pipeline errors."""

    def __init__(
        self,
        message: str,
        service: str = "memory",
        recoverable: bool = False,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        super().__init__(message, service, recoverable, suggestion, details)


class AgentError(ServiceError):
    """Agent execution errors."""

    def __init__(
        self,
        message: str,
        service: str = "agent",
        recoverable: bool = False,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        super().__init__(message, service, recoverable, suggestion, details)


class ConfigurationError(ServiceError):
    """Configuration/settings errors."""

    def __init__(
        self,
        message: str,
        service: str = "config",
        recoverable: bool = True,
        suggestion: str = "",
        details: Optional[dict] = None,
    ):
        super().__init__(message, service, recoverable, suggestion, details)
