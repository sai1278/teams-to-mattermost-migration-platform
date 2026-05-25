"""Normalization helpers shared across validation and rendering."""

from __future__ import annotations

import hashlib
import re

from ..constants import SCRUB_KEYWORDS


def slugify(value: str) -> str:
    """Convert a display-oriented value into a Mattermost-safe slug."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def stable_alias(value: str) -> str:
    """Generate a deterministic alias for anonymized identities."""

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"user-{digest}"


def scrub_message(message: str) -> str:
    """Remove sensitive text from a message when anonymization is enabled."""

    lowered = message.lower()
    if any(keyword in lowered for keyword in SCRUB_KEYWORDS):
        return "[PII SCRUBBED]"
    return message
