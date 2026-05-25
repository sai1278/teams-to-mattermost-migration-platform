"""Application-layer validation and transformation services."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..config import ParserConfig
from ..constants import (
    RECORD_TYPE_CHANNEL,
    RECORD_TYPE_POST,
    RECORD_TYPE_TEAM,
    RECORD_TYPE_USER,
    RECORD_TYPE_VERSION,
)
from ..domain.exceptions import InputValidationError
from ..domain.models import ChannelRecord, TeamRecord, UserRecord
from ..domain.normalization import scrub_message, slugify, stable_alias
from .protocols import TeamsExportSource


@dataclass(frozen=True)
class ExportValidationResult:
    """Summary produced after validating the source export."""

    team_count: int
    channel_count: int
    user_count: int
    post_count: int
    team_slugs: frozenset[str]
    user_slugs: frozenset[str]


class ExportValidationService:
    """Validate the export before any transformation work is emitted."""

    def __init__(self, config: ParserConfig):
        self._config = config

    def validate(self, source: TeamsExportSource) -> ExportValidationResult:
        errors: list[str] = []
        user_slugs: set[str] = set()
        user_team_memberships: dict[str, set[str]] = {}
        user_count = 0

        for user in source.iter_users():
            user_count += 1
            user_slug = slugify(user.username)
            if user_slug in user_slugs:
                errors.append(f"duplicate username after normalization: {user.username}")
            user_slugs.add(user_slug)
            user_team_memberships[user_slug] = {slugify(team_name) for team_name in user.teams}

        team_slugs: set[str] = set()
        channel_count = 0
        post_count = 0
        team_count = 0
        for team in source.iter_teams():
            team_count += 1
            team_slug = slugify(team.name)
            if team_slug in team_slugs:
                errors.append(f"duplicate team name after normalization: {team.name}")
            team_slugs.add(team_slug)
            channel_slugs: set[str] = set()

            for channel in team.channels:
                channel_count += 1
                channel_slug = slugify(channel.name)
                if channel_slug in channel_slugs:
                    errors.append(
                        "duplicate channel name in team "
                        f"'{team.name}' after normalization: {channel.name}"
                    )
                channel_slugs.add(channel_slug)

                for post in channel.posts:
                    post_count += 1
                    if slugify(post.username) not in user_slugs:
                        errors.append(
                            "post author "
                            f"'{post.username}' in channel '{channel.name}' is missing from users"
                        )

        for user_slug, memberships in user_team_memberships.items():
            missing_teams = memberships - team_slugs
            if missing_teams:
                errors.append(
                    f"user '{user_slug}' references unknown teams: {sorted(missing_teams)}"
                )

        if self._config.fail_on_empty_export and (team_count == 0 or user_count == 0):
            errors.append("input export must contain at least one team and one user")

        if errors:
            raise InputValidationError("\n".join(errors[:20]))

        return ExportValidationResult(
            team_count=team_count,
            channel_count=channel_count,
            user_count=user_count,
            post_count=post_count,
            team_slugs=frozenset(team_slugs),
            user_slugs=frozenset(user_slugs),
        )


class MattermostRecordService:
    """Convert validated source records into Mattermost bulk import objects."""

    def __init__(self, config: ParserConfig):
        self._config = config

    def iter_records(self, source: TeamsExportSource) -> Iterator[dict[str, Any]]:
        yield {"type": RECORD_TYPE_VERSION, "version": 1}
        yield from self.iter_team_records(source)
        yield from self.iter_channel_records(source)
        yield from self.iter_user_records(source)
        yield from self.iter_post_records(source)

    def iter_team_records(self, source: TeamsExportSource) -> Iterator[dict[str, Any]]:
        for team in source.iter_teams():
            yield {
                "type": RECORD_TYPE_TEAM,
                "team": {
                    "name": slugify(team.name),
                    "display_name": team.display_name,
                    "description": team.description,
                    "type": "O",
                },
            }

    def iter_channel_records(self, source: TeamsExportSource) -> Iterator[dict[str, Any]]:
        for team in source.iter_teams():
            for channel in team.channels:
                yield {
                    "type": RECORD_TYPE_CHANNEL,
                    "channel": {
                        "team": slugify(team.name),
                        "name": slugify(channel.name),
                        "display_name": channel.display_name,
                        "header": f"Migrated from Teams: {channel.display_name}",
                        "type": "P" if channel.is_private else "O",
                    },
                }

    def iter_user_records(self, source: TeamsExportSource) -> Iterator[dict[str, Any]]:
        for user in source.iter_users():
            username = self._normalize_username(user.username)
            yield {
                "type": RECORD_TYPE_USER,
                "user": {
                    "username": username,
                    "email": self._normalize_email(user, username),
                    "nickname": "Anonymized User" if self._config.anonymize else user.nickname,
                    "auth_service": "",
                    "password": self._config.default_password.get_secret_value(),
                    "teams": [
                        {"name": slugify(team_name), "roles": ["team_user"]}
                        for team_name in user.teams
                    ],
                },
            }

    def iter_post_records(self, source: TeamsExportSource) -> Iterator[dict[str, Any]]:
        for team in source.iter_teams():
            for channel in team.channels:
                yield from self._render_channel_posts(team, channel)

    def _render_channel_posts(
        self, team: TeamRecord, channel: ChannelRecord
    ) -> Iterator[dict[str, Any]]:
        for post in sorted(channel.posts, key=lambda item: item.timestamp_ms):
            yield {
                "type": RECORD_TYPE_POST,
                "post": {
                    "team": slugify(team.name),
                    "channel": slugify(channel.name),
                    "user": self._normalize_username(post.username),
                    "message": scrub_message(post.message)
                    if self._config.anonymize
                    else post.message,
                    "create_at": post.timestamp_ms,
                },
            }

    def _normalize_email(self, user: UserRecord, username: str) -> str:
        if self._config.anonymize:
            return f"{username}@example.invalid"
        return str(user.email).strip().lower()

    def _normalize_username(self, username: str) -> str:
        if self._config.anonymize:
            return stable_alias(username)
        return slugify(username)
