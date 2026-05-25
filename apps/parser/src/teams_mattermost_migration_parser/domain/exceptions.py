"""Exception hierarchy for parser failures."""

from __future__ import annotations


class ParserError(Exception):
    """Base class for parser-related failures."""


class ConfigurationError(ParserError):
    """Raised when runtime configuration is invalid."""


class SourceReadError(ParserError):
    """Raised when the source export cannot be read or parsed."""


class InputValidationError(ParserError):
    """Raised when the input export fails structural validation."""
