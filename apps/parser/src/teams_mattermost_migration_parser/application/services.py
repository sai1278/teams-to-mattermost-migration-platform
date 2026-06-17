"""Application-layer validation and transformation services."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import shutil
import ssl
import time
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
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
from ..domain.models import (
    AttachmentRecord,
    ChannelRecord,
    DirectChannelRecord,
    PostRecord,
    TeamRecord,
    TeamsExport,
    UserRecord,
)
from ..domain.normalization import AnonymizerPipeline, slugify, stable_alias
from ..observability.metrics import ParserMetrics
from .protocols import TeamsExportSource

LOGGER = logging.getLogger(__name__)


class _TeamsExportSourceAdapter:
    """Adapt an in-memory export aggregate to the streaming source protocol."""

    def __init__(self, export: TeamsExport):
        self._export = export

    def iter_teams(self) -> Iterator[TeamRecord]:
        return iter(self._export.teams)

    def iter_users(self) -> Iterator[UserRecord]:
        return iter(self._export.users)

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        return iter(self._export.direct_channels)

    def input_size_bytes(self) -> int:
        return 0

    def materialize(self) -> TeamsExport:
        return self._export


def _coerce_source(source: TeamsExport | TeamsExportSource) -> TeamsExportSource:
    if isinstance(source, TeamsExport):
        return _TeamsExportSourceAdapter(source)
    return source


class SlugRegistry:
    """Registry to manage and resolve unique, collision-free slugs."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def make_unique(self, value: str) -> str:
        base = slugify(value)
        candidate = base
        counter = 1
        while candidate in self._used:
            candidate = f"{base}-{counter}"
            counter += 1
        self._used.add(candidate)
        return candidate


@dataclass(frozen=True)
class ExportValidationResult:
    """Summary produced after validating the source export."""

    team_count: int
    channel_count: int
    user_count: int
    post_count: int
    direct_channel_count: int
    direct_post_count: int
    team_slugs: frozenset[str]
    user_slugs: frozenset[str]


class ExportValidationService:
    """Validate the export before any transformation work is emitted."""

    def __init__(self, config: ParserConfig):
        self._config = config

    def validate(self, source: TeamsExportSource | TeamsExport) -> ExportValidationResult:
        source = _coerce_source(source)
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
            for member in set(team.members) | set(team.owners):
                if slugify(member) not in user_slugs:
                    errors.append(
                        f"team member '{member}' in team '{team.name}' is missing from users"
                    )
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

                channel_post_ids: set[str] = set()
                for post in channel.posts:
                    post_count += 1
                    if post.id:
                        if post.id in channel_post_ids:
                            errors.append(
                                f"duplicate post id in channel '{channel.name}': {post.id}"
                            )
                        channel_post_ids.add(post.id)
                    if slugify(post.username) not in user_slugs:
                        errors.append(
                            "post author "
                            f"'{post.username}' in channel '{channel.name}' is missing from users"
                        )
                    if post.parent_id and post.parent_id not in channel_post_ids:
                        errors.append(
                            "post reply "
                            f"'{post.id or post.username}' in channel '{channel.name}' "
                            f"references unknown parent '{post.parent_id}'"
                        )
                for member in set(channel.members) | set(channel.owners):
                    if slugify(member) not in user_slugs:
                        errors.append(
                            f"channel member '{member}' in channel "
                            f"'{channel.name}' is missing from users"
                        )

        for user_slug, memberships in user_team_memberships.items():
            missing_teams = memberships - team_slugs
            if missing_teams:
                errors.append(
                    f"user '{user_slug}' references unknown teams: {sorted(missing_teams)}"
                )

        # Validate direct channels and direct posts if available
        direct_channel_count = 0
        direct_post_count = 0
        for dc in source.iter_direct_channels():
            direct_channel_count += 1
            if len(dc.members) < 2:
                errors.append(
                    f"direct channel has invalid member count: "
                    f"{len(dc.members)} (minimum 2 required)"
                )
            for member in dc.members:
                if slugify(member) not in user_slugs:
                    errors.append(f"direct channel member '{member}' is missing from users")

            for post in dc.posts:
                direct_post_count += 1
                if slugify(post.username) not in user_slugs:
                    errors.append(
                        f"direct post author '{post.username}' in DM channel is missing from users"
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
            direct_channel_count=direct_channel_count,
            direct_post_count=direct_post_count,
            team_slugs=frozenset(team_slugs),
            user_slugs=frozenset(user_slugs),
        )


class _LazyMemberships(Mapping[str, dict[str, Any]]):
    """Memory-efficient lazy-evaluating mapping of user memberships."""

    def __init__(
        self,
        user_to_teams: dict[str, set[str]],
        team_owners: dict[str, set[str]],
        channels_by_team: dict[str, list[ChannelRecord]],
        channel_members: dict[tuple[str, str], set[str]],
        channel_owners: dict[tuple[str, str], set[str]],
    ):
        self._user_to_teams = user_to_teams
        self._team_owners = team_owners
        self._channels_by_team = channels_by_team
        self._channel_members = channel_members
        self._channel_owners = channel_owners

    def __getitem__(self, key: str) -> dict[str, Any]:
        if key not in self._user_to_teams:
            raise KeyError(key)

        teams_dict = {}
        for t_name in self._user_to_teams[key]:
            if key in self._team_owners.get(t_name, set()):
                t_roles = ["team_admin", "team_user"]
            else:
                t_roles = ["team_user"]

            channels_dict = {}
            for channel in self._channels_by_team.get(t_name, []):
                c_name = channel.name
                c_owners = self._channel_owners.get((t_name, c_name), set())
                c_members = self._channel_members.get((t_name, c_name), set())

                belongs = (
                    not channel.is_private
                    or key in c_owners
                    or key in c_members
                )

                if belongs:
                    if key in c_owners:
                        c_roles = ["channel_admin", "channel_user"]
                    else:
                        c_roles = ["channel_user"]
                    channels_dict[c_name] = c_roles

            teams_dict[t_name] = {
                "roles": t_roles,
                "channels": channels_dict,
            }
        return {"teams": teams_dict}

    def __iter__(self) -> Iterator[str]:
        return iter(self._user_to_teams)

    def __len__(self) -> int:
        return len(self._user_to_teams)


class MattermostRecordService:
    """Convert validated source records into Mattermost bulk import objects."""

    def __init__(self, config: ParserConfig, metrics: ParserMetrics | None = None):
        self._config = config
        self._metrics = metrics
        self._mappings_built = False
        self._team_slugs = SlugRegistry()
        self._user_slugs = SlugRegistry()
        self._channel_registries: dict[str, SlugRegistry] = {}
        self._team_slug_map: dict[str, str] = {}
        self._channel_slug_map: dict[tuple[str, str], str] = {}
        self._user_slug_map: dict[str, str] = {}

    def _build_mappings(self, source: TeamsExportSource | TeamsExport) -> None:
        source = _coerce_source(source)
        if self._mappings_built:
            return

        # 1. Users
        salt = (
            self._config.anonymize_salt.get_secret_value().encode("utf-8")
            if self._config.anonymize
            else None
        )
        for user in source.iter_users():
            if self._config.anonymize:
                resolved_user = stable_alias(user.username, salt=salt)
            else:
                resolved_user = self._user_slugs.make_unique(user.username)
            self._user_slug_map[user.username] = resolved_user

        # 2. Teams and Channels
        for team in source.iter_teams():
            resolved_team = self._team_slugs.make_unique(team.name)
            self._team_slug_map[team.name] = resolved_team
            self._channel_registries[resolved_team] = SlugRegistry()

            for channel in team.channels:
                resolved_channel = self._channel_registries[resolved_team].make_unique(channel.name)
                self._channel_slug_map[(team.name, channel.name)] = resolved_channel

        self._mappings_built = True

    def _resolve_memberships(
        self, source: TeamsExportSource | TeamsExport
    ) -> Mapping[str, dict[str, Any]]:
        source = _coerce_source(source)

        user_to_teams: dict[str, set[str]] = {}
        team_owners: dict[str, set[str]] = {}
        channels_by_team: dict[str, list[ChannelRecord]] = {}
        channel_members: dict[tuple[str, str], set[str]] = {}
        channel_owners: dict[tuple[str, str], set[str]] = {}

        # 1. Initialize from explicit users
        for user in source.iter_users():
            if user.teams:
                user_to_teams.setdefault(user.username, set()).update(user.teams)

        # 2. Build indexes from teams & channels records
        for team in source.iter_teams():
            t_name = team.name
            team_owners[t_name] = set(team.owners)
            channels_by_team[t_name] = list(team.channels)

            # Explicit team members/owners
            for u in team.owners:
                user_to_teams.setdefault(u, set()).add(t_name)
            for u in team.members:
                user_to_teams.setdefault(u, set()).add(t_name)

            for channel in team.channels:
                c_name = channel.name
                c_owners_set = set(channel.owners)
                c_members_set = set(channel.members)
                channel_owners[(t_name, c_name)] = c_owners_set
                channel_members[(t_name, c_name)] = c_members_set

                # Any channel member/owner belongs to the team
                for u in c_owners_set:
                    user_to_teams.setdefault(u, set()).add(t_name)
                for u in c_members_set:
                    user_to_teams.setdefault(u, set()).add(t_name)

        return _LazyMemberships(
            user_to_teams=user_to_teams,
            team_owners=team_owners,
            channels_by_team=channels_by_team,
            channel_members=channel_members,
            channel_owners=channel_owners,
        )

    def _process_attachment(
        self, attachment: AttachmentRecord, input_dir: Path, output_dir: Path
    ) -> str | None:
        """Copy local file or download remote attachment to output attachments directory."""
        h = hashlib.sha256(attachment.path.encode("utf-8")).hexdigest()[:8]
        orig_name = Path(attachment.path).name
        # Sanitize filename
        safe_orig_name = re.sub(r"[^a-zA-Z0-9.-]+", "_", orig_name)
        if not safe_orig_name:
            safe_orig_name = "file"
        safe_name = f"{h}_{safe_orig_name}"
        dest_path = output_dir / safe_name

        if dest_path.exists():
            return f"attachments/{safe_name}"

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        src = attachment.url or attachment.path
        is_url = src.startswith("http://") or src.startswith("https://")
        max_retries = 3
        backoff = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                if is_url:
                    req = urllib.request.Request(src, headers={"User-Agent": "TMMP-Parser/1.0"})
                    # SEC: enforce SSL/TLS certificate validation
                    context = ssl.create_default_context()
                    with (
                        urllib.request.urlopen(req, timeout=10, context=context) as response,
                        open(dest_path, "wb") as out_file,
                    ):
                        shutil.copyfileobj(response, out_file)
                else:
                    src_path = Path(src)
                    if not src_path.is_absolute():
                        src_path = input_dir / src_path
                    if not src_path.exists():
                        raise FileNotFoundError(f"Local file {src_path} does not exist")
                    shutil.copy2(src_path, dest_path)
                if self._metrics:
                    self._metrics.observe_attachment("success")
                return f"attachments/{safe_name}"
            except Exception as exc:
                LOGGER.warning(
                    f"Attempt {attempt}/{max_retries} failed to process attachment {src}: {exc}"
                )
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** (attempt - 1)))
                else:
                    if self._metrics:
                        self._metrics.observe_attachment("failed")
                    LOGGER.error(
                        f"Failed to process attachment {src} after {max_retries} attempts: {exc}",
                        extra={
                            "event": "attachment_failed",
                            "details": {"src": src, "error": str(exc)},
                        },
                    )
        return None

    def _source_post_key(
        self, team: TeamRecord, channel: ChannelRecord, post: PostRecord, index: int
    ) -> str:
        if post.id:
            return post.id
        payload = "|".join(
            (
                team.name,
                channel.name,
                str(index),
                str(post.timestamp_ms),
                post.username,
                post.message,
            )
        )
        salt = self._config.anonymize_salt.get_secret_value().encode("utf-8")
        digest = hmac.new(salt, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
        return f"source-post-{digest}"

    def _post_import_id(self, team: TeamRecord, channel: ChannelRecord, source_key: str) -> str:
        payload = "|".join(
            (
                self._team_slug_map[team.name],
                self._channel_slug_map[(team.name, channel.name)],
                source_key,
            )
        )
        salt = self._config.anonymize_salt.get_secret_value().encode("utf-8")
        digest = hmac.new(salt, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
        return f"post-{digest}"

    def _direct_post_id(self, dc: DirectChannelRecord, post: PostRecord, index: int) -> str:
        payload = "|".join(
            (
                ",".join(sorted(dc.members)),
                str(index),
                str(post.timestamp_ms),
                post.username,
                post.message,
            )
        )
        salt = self._config.anonymize_salt.get_secret_value().encode("utf-8")
        digest = hmac.new(salt, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
        return f"direct-post-{digest}"

    def _resolve_thread_root_key(self, source_key: str, parent_map: dict[str, str]) -> str:
        current = source_key
        seen: set[str] = {source_key}
        while True:
            parent = parent_map.get(current)
            if not parent or parent in seen:
                return current
            seen.add(parent)
            current = parent

    def iter_records(self, source: TeamsExportSource | TeamsExport) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        self._build_mappings(source)

        # Collect and pre-download all attachments concurrently
        attachments_to_download = []
        seen_attachments = set()
        for team in source.iter_teams():
            for channel in team.channels:
                for post in channel.posts:
                    for att in post.attachments:
                        if att.path not in seen_attachments:
                            seen_attachments.add(att.path)
                            attachments_to_download.append(att)
        for dc in source.iter_direct_channels():
            for post in dc.posts:
                for att in post.attachments:
                    if att.path not in seen_attachments:
                        seen_attachments.add(att.path)
                        attachments_to_download.append(att)

        if attachments_to_download:
            input_dir = self._config.input_path.parent
            output_dir = self._config.output_path.parent / "attachments"
            from concurrent.futures import ThreadPoolExecutor

            max_workers = getattr(self._config, "attachment_workers", 4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(self._process_attachment, att, input_dir, output_dir)
                    for att in attachments_to_download
                ]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:
                        LOGGER.warning(f"Concurrent attachment download failed: {exc}")

        yield {"type": RECORD_TYPE_VERSION, "version": 1}
        yield from self.iter_team_records(source)
        yield from self.iter_channel_records(source)
        yield from self.iter_user_records(source)
        yield from self.iter_post_records(source)
        yield from self.iter_direct_channel_records(source)
        yield from self.iter_direct_post_records(source)

    def iter_team_records(
        self, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        self._build_mappings(source)
        for team in source.iter_teams():
            yield {
                "type": RECORD_TYPE_TEAM,
                "team": {
                    "name": self._team_slug_map[team.name],
                    "display_name": team.display_name,
                    "description": team.description,
                    "type": "O",
                },
            }

    def iter_channel_records(
        self, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        self._build_mappings(source)
        for team in source.iter_teams():
            team_slug = self._team_slug_map[team.name]
            for channel in team.channels:
                yield {
                    "type": RECORD_TYPE_CHANNEL,
                    "channel": {
                        "team": team_slug,
                        "name": self._channel_slug_map[(team.name, channel.name)],
                        "display_name": channel.display_name,
                        "header": f"Migrated from Teams: {channel.display_name}",
                        "type": "P" if channel.is_private else "O",
                    },
                }

    def iter_user_records(
        self, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        self._build_mappings(source)
        memberships = self._resolve_memberships(source)

        for user in source.iter_users():
            username = self._normalize_username(user.username)
            user_data: dict[str, Any] = {
                "username": username,
                "email": self._normalize_email(user, username),
                "nickname": "Anonymized User" if self._config.anonymize else user.nickname,
            }

            if self._config.auth_service:
                user_data["auth_service"] = self._config.auth_service
                if self._config.auth_data_field == "email":
                    user_data["auth_data"] = user.email
                else:
                    user_data["auth_data"] = username
            # SEC: Never export plaintext passwords to JSONL output.
            # Password provisioning is handled by Mattermost server-side
            # using TMMP_DEFAULT_PASSWORD env var at import time.

            # Map resolved memberships with roles and channels
            user_membership_data = memberships.get(user.username, {}).get("teams", {})
            teams_list: list[dict[str, Any]] = []
            for t_name, t_info in user_membership_data.items():
                channels_list: list[dict[str, Any]] = []
                for c_name, c_roles in t_info["channels"].items():
                    channels_list.append(
                        {
                            "name": self._channel_slug_map.get((t_name, c_name), slugify(c_name)),
                            "roles": c_roles,
                        }
                    )
                teams_list.append(
                    {
                        "name": self._team_slug_map.get(t_name, slugify(t_name)),
                        "roles": t_info["roles"],
                        "channels": channels_list,
                    }
                )
            user_data["teams"] = teams_list

            yield {
                "type": RECORD_TYPE_USER,
                "user": user_data,
            }

    def iter_post_records(
        self, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        for team in source.iter_teams():
            for channel in team.channels:
                yield from self._render_channel_posts(team, channel, source)

    def _render_channel_posts(
        self, team: TeamRecord, channel: ChannelRecord, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        self._build_mappings(source)  # Ensure mappings are built
        input_dir = self._config.input_path.parent
        output_dir = self._config.output_path.parent / "attachments"
        usernames = list(self._user_slug_map.keys())
        salt = (
            self._config.anonymize_salt.get_secret_value().encode("utf-8")
            if self._config.anonymize
            else None
        )
        anonymizer = AnonymizerPipeline(
            usernames=usernames if self._config.anonymize else [],
            salt=salt
        )
        post_entries: list[tuple[int, PostRecord, str]] = []
        parent_map: dict[str, str] = {}
        for index, post in enumerate(channel.posts):
            source_key = self._source_post_key(team, channel, post, index)
            post_entries.append((index, post, source_key))
            if post.parent_id:
                parent_map[source_key] = post.parent_id

        root_map = {
            source_key: self._resolve_thread_root_key(source_key, parent_map)
            for _, _, source_key in post_entries
        }
        root_timestamps: dict[str, int] = {}
        for _, post, source_key in post_entries:
            if root_map[source_key] == source_key:
                root_timestamps[source_key] = post.timestamp_ms

        import_ids = {
            source_key: self._post_import_id(team, channel, source_key)
            for _, _, source_key in post_entries
        }

        def sort_key(entry: tuple[int, PostRecord, str]) -> tuple[int, str, int, int, int, str]:
            index, post, source_key = entry
            root_key = root_map[source_key]
            root_timestamp = root_timestamps.get(root_key, post.timestamp_ms)
            return (
                root_timestamp,
                root_key,
                0 if source_key == root_key else 1,
                post.timestamp_ms,
                index,
                source_key,
            )

        for _index, post, source_key in sorted(post_entries, key=sort_key):
            post_data: dict[str, Any] = {
                "id": import_ids[source_key],
                "import_id": import_ids[source_key],
                "team": self._team_slug_map[team.name],
                "channel": self._channel_slug_map[(team.name, channel.name)],
                "user": self._normalize_username(post.username),
                "message": anonymizer.anonymize(post.message)
                if self._config.anonymize
                else post.message,
                "create_at": post.timestamp_ms,
            }

            if post.parent_id:
                root_key = root_map[source_key]
                root_import_id = import_ids.get(root_key)
                if root_import_id and root_import_id != import_ids[source_key]:
                    post_data["root_id"] = root_import_id
                else:
                    LOGGER.warning(
                        "unresolved reply chain encountered while rendering channel posts",
                        extra={
                            "event": "orphan_reply",
                            "details": {
                                "team": team.name,
                                "channel": channel.name,
                                "post_id": post.id,
                                "parent_id": post.parent_id,
                            },
                        },
                    )

            if post.attachments:
                attachments_list = []
                file_ids: list[str] = []
                for att in post.attachments:
                    rel_path = self._process_attachment(att, input_dir, output_dir)
                    if rel_path:
                        file_id = Path(rel_path).name
                        file_ids.append(file_id)
                        attachments_list.append({"path": rel_path, "file_id": file_id})
                if attachments_list:
                    post_data["attachments"] = attachments_list
                    post_data["file_ids"] = file_ids

            yield {
                "type": RECORD_TYPE_POST,
                "post": post_data,
            }

    def iter_direct_channel_records(
        self, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        self._build_mappings(source)
        for dc in source.iter_direct_channels():
            normalized_members = [self._normalize_username(m) for m in dc.members]
            yield {
                "type": "direct_channel",
                "direct_channel": {
                    "members": normalized_members,
                },
            }

    def iter_direct_post_records(
        self, source: TeamsExportSource | TeamsExport
    ) -> Iterator[dict[str, Any]]:
        source = _coerce_source(source)
        self._build_mappings(source)
        input_dir = self._config.input_path.parent
        output_dir = self._config.output_path.parent / "attachments"
        usernames = list(self._user_slug_map.keys())
        salt = self._config.anonymize_salt.get_secret_value().encode("utf-8") if self._config.anonymize else None
        anonymizer = AnonymizerPipeline(
            usernames=usernames if self._config.anonymize else [],
            salt=salt
        )

        for dc in source.iter_direct_channels():
            normalized_members = [self._normalize_username(m) for m in dc.members]
            for index, post in enumerate(sorted(dc.posts, key=lambda item: item.timestamp_ms)):
                post_id = self._direct_post_id(dc, post, index)
                post_data = {
                    "id": post_id,
                    "import_id": post_id,
                    "channel_members": normalized_members,
                    "user": self._normalize_username(post.username),
                    "message": anonymizer.anonymize(post.message)
                    if self._config.anonymize
                    else post.message,
                    "create_at": post.timestamp_ms,
                }

                if post.attachments:
                    attachments_list = []
                    file_ids: list[str] = []
                    for att in post.attachments:
                        rel_path = self._process_attachment(att, input_dir, output_dir)
                        if rel_path:
                            file_id = Path(rel_path).name
                            file_ids.append(file_id)
                            attachments_list.append({"path": rel_path, "file_id": file_id})
                    if attachments_list:
                        post_data["attachments"] = attachments_list
                        post_data["file_ids"] = file_ids

                yield {
                    "type": "direct_post",
                    "direct_post": post_data,
                }

    def _normalize_email(self, user: UserRecord, username: str) -> str:
        if self._config.anonymize:
            return f"{username}@example.invalid"
        return str(user.email).strip().lower()

    def _normalize_username(self, username: str) -> str:
        if username in self._user_slug_map:
            return self._user_slug_map[username]
        if self._config.anonymize:
            salt = self._config.anonymize_salt.get_secret_value().encode("utf-8")
            return stable_alias(username, salt=salt)
        return slugify(username)
