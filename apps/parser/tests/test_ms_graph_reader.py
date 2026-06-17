from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.domain.exceptions import SourceReadError
from teams_mattermost_migration_parser.infrastructure.ms_graph_reader import MSGraphExportSource


def test_ms_graph_reader_requires_credentials() -> None:
    config = ParserConfig.from_inputs(
        input_path=Path("ms-graph"),
        output_path=Path("output.jsonl"),
        ms_graph_tenant_id="common",
        ms_graph_client_id=None,
        ms_graph_client_secret=None,
    )
    source = MSGraphExportSource(config)
    msg = "MS Graph client_id and client_secret must be configured"
    with pytest.raises(SourceReadError, match=msg):
        list(source.iter_users())


def test_ms_graph_reader_fetch_success() -> None:
    config = ParserConfig.from_inputs(
        input_path=Path("ms-graph"),
        output_path=Path("output.jsonl"),
        ms_graph_tenant_id="common",
        ms_graph_client_id="mock-client-id",
        ms_graph_client_secret="mock-client-secret",
    )
    source = MSGraphExportSource(config)

    # Prepare mocked responses
    mock_responses = {
        "https://login.microsoftonline.com/common/oauth2/v2.0/token": {
            "access_token": "mock-token"
        },
        "https://graph.microsoft.com/v1.0/users": {
            "value": [
                {
                    "userPrincipalName": "john.doe@company.com",
                    "mail": "john.doe@company.com",
                    "displayName": "John Doe",
                },
                {
                    "userPrincipalName": "sarah.khan@company.com",
                    "mail": "sarah.khan@company.com",
                    "displayName": "Sarah Khan",
                },
            ]
        },
        "https://graph.microsoft.com/v1.0/groups?$filter="
        "resourceProvisioningOptions/any(x:x eq 'Team')": {
            "value": [
                {
                    "id": "team-id-1",
                    "mailNickname": "it-team",
                    "displayName": "IT Team",
                    "description": "IT Dept",
                }
            ]
        },
        "https://graph.microsoft.com/v1.0/groups/team-id-1/owners": {
            "value": [{"userPrincipalName": "john.doe@company.com"}]
        },
        "https://graph.microsoft.com/v1.0/groups/team-id-1/members": {
            "value": [
                {"userPrincipalName": "john.doe@company.com"},
                {"userPrincipalName": "sarah.khan@company.com"},
            ]
        },
        "https://graph.microsoft.com/v1.0/teams/team-id-1/channels": {
            "value": [
                {"id": "channel-id-1", "displayName": "general", "membershipType": "standard"}
            ]
        },
        "https://graph.microsoft.com/v1.0/teams/team-id-1/channels/channel-id-1/messages": {
            "value": [
                {
                    "id": "msg-id-1",
                    "from": {"user": {"userPrincipalName": "john.doe@company.com"}},
                    "createdDateTime": "2026-06-17T12:00:00Z",
                    "body": {"content": "Hello IT Team"},
                    "replyToId": None,
                    "attachments": [
                        {"name": "test.txt", "contentUrl": "http://example.com/test.txt"}
                    ],
                }
            ]
        },
        "https://graph.microsoft.com/v1.0/chats": {"value": [{"id": "chat-id-1"}]},
        "https://graph.microsoft.com/v1.0/chats/chat-id-1/members": {
            "value": [
                {"userPrincipalName": "john.doe@company.com"},
                {"userPrincipalName": "sarah.khan@company.com"},
            ]
        },
        "https://graph.microsoft.com/v1.0/chats/chat-id-1/messages": {
            "value": [
                {
                    "id": "chat-msg-id-1",
                    "from": {"user": {"userPrincipalName": "john.doe@company.com"}},
                    "createdDateTime": "2026-06-17T12:05:00Z",
                    "body": {"content": "Hi Sarah"},
                    "attachments": [],
                }
            ]
        },
    }

    def mock_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        url = req if isinstance(req, str) else req.full_url
        if url in mock_responses:
            resp = MagicMock()
            resp.__enter__.return_value = resp
            resp.read.return_value = json.dumps(mock_responses[url]).encode("utf-8")
            return resp
        raise Exception(f"Unexpected URL request: {url}")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        users = list(source.iter_users())
        teams = list(source.iter_teams())
        direct_channels = list(source.iter_direct_channels())
        size = source.input_size_bytes()
        materialized = source.materialize()

    assert size == 0
    assert materialized is not None
    assert len(materialized.users) == 2
    assert len(users) == 2
    assert users[0].username == "john.doe"
    assert users[0].email == "john.doe@company.com"
    assert users[0].nickname == "John Doe"
    assert users[0].teams == ("it-team",)

    assert len(teams) == 1
    assert teams[0].name == "it-team"
    assert len(teams[0].channels) == 1
    assert teams[0].channels[0].name == "general"
    assert len(teams[0].channels[0].posts) == 1
    assert teams[0].channels[0].posts[0].message == "Hello IT Team"
    assert teams[0].channels[0].posts[0].attachments[0].name == "test.txt"

    assert len(direct_channels) == 1
    assert set(direct_channels[0].members) == {"john.doe", "sarah.khan"}
    assert len(direct_channels[0].posts) == 1
    assert direct_channels[0].posts[0].message == "Hi Sarah"


def test_ms_graph_reader_auth_failure() -> None:
    config = ParserConfig.from_inputs(
        input_path=Path("ms-graph"),
        output_path=Path("output.jsonl"),
        ms_graph_tenant_id="common",
        ms_graph_client_id="mock-client-id",
        ms_graph_client_secret="mock-client-secret",
    )
    source = MSGraphExportSource(config)

    with (
        patch("urllib.request.urlopen", side_effect=URLError("Connection refused")),
        pytest.raises(SourceReadError, match="MS Graph authentication failed"),
    ):
        list(source.iter_users())
