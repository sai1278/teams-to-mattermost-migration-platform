import json
import logging
import urllib.request
import urllib.parse
from collections.abc import Iterator
from typing import Any
from pathlib import Path

from ..config import ParserConfig
from ..domain.exceptions import SourceReadError
from ..domain.models import (
    AttachmentRecord,
    ChannelRecord,
    DirectChannelRecord,
    PostRecord,
    TeamRecord,
    TeamsExport,
    UserRecord,
)

LOGGER = logging.getLogger(__name__)


class MSGraphExportSource:
    """Read migration data directly from Microsoft Graph API."""

    def __init__(self, config: ParserConfig):
        self.config = config
        self.tenant_id = config.ms_graph_tenant_id or "common"
        self.client_id = config.ms_graph_client_id
        self.client_secret = config.ms_graph_client_secret.get_secret_value() if config.ms_graph_client_secret else None
        
        # In-memory cache to support materialize() and caching teams/users mapping
        self._users: list[UserRecord] = []
        self._teams: list[TeamRecord] = []
        self._direct_channels: list[DirectChannelRecord] = []
        self._access_token: str | None = None
        self._fetched = False

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise SourceReadError("MS Graph client_id and client_secret must be configured")

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default"
        }).encode("utf-8")

        req = urllib.request.Request(token_url, data=data)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                token_data = json.loads(resp.read().decode("utf-8"))
                self._access_token = token_data["access_token"]
                return self._access_token
        except Exception as exc:
            raise SourceReadError(f"MS Graph authentication failed: {exc}") from exc

    def _api_get(self, url: str) -> dict[str, Any]:
        """Perform an authenticated GET request to the MS Graph API."""
        token = self._get_access_token()
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "TMMP-Parser/1.0"
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return result
        except Exception as exc:
            raise SourceReadError(f"MS Graph API call to {url} failed: {exc}") from exc

    def _api_get_all(self, url: str) -> list[dict[str, Any]]:
        """Fetch all items from an endpoint, following nextLink paging."""
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        while next_url:
            data = self._api_get(next_url)
            items.extend(data.get("value", []))
            next_url = data.get("@odata.nextLink")
        return items

    def _fetch_all(self) -> None:
        if self._fetched:
            return

        # 1. Fetch Users
        users_raw = self._api_get_all("https://graph.microsoft.com/v1.0/users")
        
        # 2. Fetch Teams (Groups backed by Teams)
        groups_url = "https://graph.microsoft.com/v1.0/groups?$filter=resourceProvisioningOptions/any(x:x eq 'Team')"
        teams_raw = self._api_get_all(groups_url)

        # User to teams membership mapping
        user_teams: dict[str, list[str]] = {}

        self._teams = []
        for team_data in teams_raw:
            team_id = team_data["id"]
            team_name = team_data.get("mailNickname") or team_id
            display_name = team_data.get("displayName") or team_name
            description = team_data.get("description") or ""

            # Fetch owners
            owners_raw = self._api_get_all(f"https://graph.microsoft.com/v1.0/groups/{team_id}/owners")
            owners = []
            for owner in owners_raw:
                upn = owner.get("userPrincipalName")
                if upn:
                    username = upn.split("@")[0]
                    owners.append(username)
                    user_teams.setdefault(username, []).append(team_name)

            # Fetch members
            members_raw = self._api_get_all(f"https://graph.microsoft.com/v1.0/groups/{team_id}/members")
            members = []
            for member in members_raw:
                upn = member.get("userPrincipalName")
                if upn:
                    username = upn.split("@")[0]
                    members.append(username)
                    user_teams.setdefault(username, []).append(team_name)

            # Fetch channels
            channels_raw = self._api_get_all(f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels")
            channels = []
            for chan in channels_raw:
                chan_id = chan["id"]
                chan_name = chan.get("displayName") or chan_id
                is_private = chan.get("membershipType") == "private"

                # Fetch channel messages
                msg_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{chan_id}/messages"
                messages_raw = self._api_get_all(msg_url)
                posts = []
                for msg in messages_raw:
                    msg_id = msg.get("id")
                    from_user = msg.get("from", {}).get("user", {})
                    author_upn = from_user.get("userPrincipalName")
                    if not author_upn:
                        continue
                    author = author_upn.split("@")[0]
                    
                    created_at_str: str | None = msg.get("createdDateTime")
                    try:
                        from datetime import datetime
                        if created_at_str is None:
                            raise ValueError("missing createdDateTime")
                        dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        timestamp_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        timestamp_ms = 0

                    body = msg.get("body", {}).get("content") or ""
                    
                    # Fetch attachments
                    attachments = []
                    for att in msg.get("attachments", []):
                        attachments.append(AttachmentRecord(
                            name=att.get("name") or "file",
                            path=att.get("name") or "file",
                            url=att.get("contentUrl")
                        ))

                    posts.append(PostRecord(
                        id=msg_id,
                        username=author,
                        message=body,
                        timestamp_ms=timestamp_ms,
                        parent_id=msg.get("replyToId"),
                        attachments=tuple(attachments)
                    ))

                channels.append(ChannelRecord(
                    name=chan_name,
                    display_name=chan_name,
                    is_private=is_private,
                    posts=tuple(posts),
                    members=tuple(members),
                    owners=tuple(owners)
                ))

            self._teams.append(TeamRecord(
                name=team_name,
                display_name=display_name,
                description=description,
                channels=tuple(channels),
                members=tuple(members),
                owners=tuple(owners)
            ))

        # Build UserRecords
        self._users = []
        for user_data in users_raw:
            upn = user_data.get("userPrincipalName")
            if not upn:
                continue
            username = upn.split("@")[0]
            email = user_data.get("mail") or upn
            nickname = user_data.get("displayName") or username
            teams_joined = tuple(sorted(list(set(user_teams.get(username, [])))))
            
            self._users.append(UserRecord(
                username=username,
                email=email,
                nickname=nickname,
                teams=teams_joined
            ))

        # 3. Fetch Chats (Direct Message channels)
        chats_raw = self._api_get_all("https://graph.microsoft.com/v1.0/chats")
        self._direct_channels = []
        for chat_data in chats_raw:
            chat_id = chat_data["id"]
            
            # Fetch members
            chat_members_raw = self._api_get_all(f"https://graph.microsoft.com/v1.0/chats/{chat_id}/members")
            chat_members = []
            for member in chat_members_raw:
                upn = member.get("userPrincipalName") or member.get("email")
                if upn:
                    chat_members.append(upn.split("@")[0])

            if len(chat_members) < 2:
                continue

            # Fetch messages
            chat_messages_raw = self._api_get_all(f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages")
            posts = []
            for msg in chat_messages_raw:
                msg_id = msg.get("id")
                from_user = msg.get("from", {}).get("user", {})
                author_upn = from_user.get("userPrincipalName")
                if not author_upn:
                    continue
                author = author_upn.split("@")[0]

                created_at_str = msg.get("createdDateTime")
                try:
                    from datetime import datetime
                    if created_at_str is None:
                        raise ValueError("missing createdDateTime")
                    dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    timestamp_ms = int(dt.timestamp() * 1000)
                except Exception:
                    timestamp_ms = 0

                body = msg.get("body", {}).get("content") or ""
                
                attachments = []
                for att in msg.get("attachments", []):
                    attachments.append(AttachmentRecord(
                        name=att.get("name") or "file",
                        path=att.get("name") or "file",
                        url=att.get("contentUrl")
                    ))

                posts.append(PostRecord(
                    id=msg_id,
                    username=author,
                    message=body,
                    timestamp_ms=timestamp_ms,
                    attachments=tuple(attachments)
                ))

            self._direct_channels.append(DirectChannelRecord(
                members=tuple(chat_members),
                posts=tuple(posts)
            ))

        self._fetched = True

    def iter_teams(self) -> Iterator[TeamRecord]:
        self._fetch_all()
        yield from self._teams

    def iter_users(self) -> Iterator[UserRecord]:
        self._fetch_all()
        yield from self._users

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        self._fetch_all()
        yield from self._direct_channels

    def input_size_bytes(self) -> int:
        return 0

    def materialize(self) -> TeamsExport:
        self._fetch_all()
        return TeamsExport(
            teams=tuple(self._teams),
            users=tuple(self._users),
            direct_channels=tuple(self._direct_channels),
        )
