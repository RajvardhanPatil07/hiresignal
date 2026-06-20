"""Custom exceptions for the HireSignal application."""

from __future__ import annotations


class HireSignalError(Exception):
    """Base exception for all HireSignal errors."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class ResumeParsingError(HireSignalError):
    """Raised when resume parsing fails."""

    def __init__(self, message: str = "Failed to parse resume") -> None:
        super().__init__(message, status_code=422)


class FileValidationError(HireSignalError):
    """Raised when uploaded file validation fails."""

    def __init__(self, message: str = "Invalid file") -> None:
        super().__init__(message, status_code=400)


class ScoringError(HireSignalError):
    """Raised when scoring computation fails."""

    def __init__(self, message: str = "Scoring failed") -> None:
        super().__init__(message, status_code=500)


class SocialMediaError(HireSignalError):
    """Raised when social media fetching fails."""

    def __init__(self, message: str = "Social media analysis failed") -> None:
        super().__init__(message, status_code=500)


class AuthenticationError(HireSignalError):
    """Raised when API key authentication fails."""

    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(message, status_code=401)


class RateLimitError(HireSignalError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, status_code=429)


class CacheError(HireSignalError):
    """Raised when cache operation fails."""

    def __init__(self, message: str = "Cache operation failed") -> None:
        super().__init__(message, status_code=500)


class LLMError(HireSignalError):
    """Raised when LLM call fails."""

    def __init__(self, message: str = "LLM processing failed") -> None:
        super().__init__(message, status_code=502)
