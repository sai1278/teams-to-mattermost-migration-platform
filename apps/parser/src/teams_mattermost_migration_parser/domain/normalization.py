"""Normalization helpers shared across validation and rendering."""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from ..constants import SCRUB_KEYWORDS


def slugify(value: str) -> str:
    """Convert a display-oriented value into a Mattermost-safe slug."""
    if not value:
        return "default-slug"

    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
        return f"fallback-{digest}"
    return slug



def stable_alias(value: str, salt: bytes | None = None) -> str:
    """Generate a deterministic alias for anonymized identities."""
    if salt is None:
        salt_str = (
            os.environ.get("TMMP_ANONYMIZE_SALT")
            or os.environ.get("TMMP_ANONYMIZATION_SALT")
            or "default-anonymization-salt-value"
        )
        salt = salt_str.encode("utf-8")
    digest = hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    return f"user-{digest}"


class AnonymizerPipeline:
    """Extensible pipeline to detect and redact PII from messages."""

    def __init__(self, usernames: list[str] | None = None, salt: bytes | None = None):
        self.usernames = usernames or []
        self.salt = salt
        self.email_regex = re.compile(
            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE
        )
        self.phone_regex = re.compile(
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        )
        self.employee_id_regex = re.compile(r"\b(?:EMP|emp)-\d{4,8}\b|\bE\d{5,8}\b")
        self.url_regex = re.compile(r"https?://[^\s]+")
        self.credit_card_regex = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
        self.ip_regex = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

    def anonymize(self, message: str) -> str:
        if not message:
            return message

        # Backwards-compatible check: if message contains block keywords
        lowered = message.lower()
        if any(keyword in lowered for keyword in SCRUB_KEYWORDS):
            return "[PII SCRUBBED]"

        # Redact credit cards
        message = self.credit_card_regex.sub("[REDACTED CREDIT CARD]", message)
        # Redact emails
        message = self.email_regex.sub("[REDACTED EMAIL]", message)
        # Redact phone numbers
        message = self.phone_regex.sub("[REDACTED PHONE]", message)
        # Redact employee IDs
        message = self.employee_id_regex.sub("[REDACTED EMPLOYEE ID]", message)
        # Redact URLs
        message = self.url_regex.sub("[REDACTED URL]", message)
        # Redact IPs
        message = self.ip_regex.sub("[REDACTED IP]", message)

        # Redact usernames
        for username in self.usernames:
            if not username:
                continue
            alias = stable_alias(username, salt=self.salt)
            pattern = re.compile(rf"\b{re.escape(username)}\b", re.IGNORECASE)
            message = pattern.sub(alias, message)

        return message


def scrub_message(message: str) -> str:
    """Remove sensitive text from a message when anonymization is enabled."""
    pipeline = AnonymizerPipeline()
    return pipeline.anonymize(message)
