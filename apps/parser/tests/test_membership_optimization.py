from __future__ import annotations

from pathlib import Path

import pytest

from teams_mattermost_migration_parser.application.services import (
    MattermostRecordService,
    _LazyMemberships,
)
from teams_mattermost_migration_parser.config import ParserConfig
from teams_mattermost_migration_parser.domain.models import (
    ChannelRecord,
    TeamRecord,
    TeamsExport,
    UserRecord,
)


def _config(tmp_path: Path) -> ParserConfig:
    return ParserConfig.from_inputs(
        input_path=tmp_path / "source" / "input.json",
        output_path=tmp_path / "output" / "import.jsonl",
        metrics_output_path=tmp_path / "metrics" / "parser.prom",
    )

def test_lazy_memberships_mapping_interface() -> None:
    # Set up mock input data for _LazyMemberships
    user_to_teams = {"user-1": {"team-1"}, "user-2": {"team-1", "team-2"}}
    team_owners = {"team-1": {"user-1"}, "team-2": {"user-2"}}
    channels_by_team = {
        "team-1": [
            ChannelRecord(name="general", display_name="General", is_private=False),
            ChannelRecord(
                name="private-c",
                display_name="Private",
                is_private=True,
                members=("user-1",),
            ),
        ],
        "team-2": [
            ChannelRecord(name="random", display_name="Random", is_private=False),
        ]
    }
    channel_members = {("team-1", "private-c"): {"user-1"}}
    channel_owners = {("team-1", "private-c"): set()}

    memberships = _LazyMemberships(
        user_to_teams=user_to_teams,
        team_owners=team_owners,
        channels_by_team=channels_by_team,
        channel_members=channel_members,
        channel_owners=channel_owners,
    )

    # 1. Test Mapping lengths and keys
    assert len(memberships) == 2
    assert set(memberships) == {"user-1", "user-2"}
    assert "user-1" in memberships
    assert "user-3" not in memberships

    # 2. Test getitem and get
    with pytest.raises(KeyError):
        _ = memberships["user-3"]

    user1_info = memberships["user-1"]
    assert "teams" in user1_info
    assert "team-1" in user1_info["teams"]
    assert user1_info["teams"]["team-1"]["roles"] == ["team_admin", "team_user"]

    # user-1 belongs to team-1, general (public) and private-c (private, where they are member)
    channels1 = user1_info["teams"]["team-1"]["channels"]
    assert "general" in channels1
    assert channels1["general"] == ["channel_user"]
    assert "private-c" in channels1
    assert channels1["private-c"] == ["channel_user"]

    user2_info = memberships.get("user-2")
    assert user2_info is not None
    assert "team-1" in user2_info["teams"]
    assert "team-2" in user2_info["teams"]
    # user-2 is owner of team-2, but member of team-1
    assert user2_info["teams"]["team-1"]["roles"] == ["team_user"]
    assert user2_info["teams"]["team-2"]["roles"] == ["team_admin", "team_user"]

    # user-2 does not belong to private-c in team-1
    assert "general" in user2_info["teams"]["team-1"]["channels"]
    assert "private-c" not in user2_info["teams"]["team-1"]["channels"]

def test_lazy_memberships_large_scale_benchmark(tmp_path: Path) -> None:
    # Test that we can generate membership records for large organizations efficiently
    user_count = 1000
    team_count = 10
    channels_per_team = 20

    users = [
        UserRecord(
            username=f"user-{i}",
            email=f"user-{i}@company.com",
            nickname=f"User {i}",
            teams=(f"team-{i % team_count}",),
        )
        for i in range(user_count)
    ]

    teams = [
        TeamRecord(
            name=f"team-{t}",
            display_name=f"Team {t}",
            members=[f"user-{i}" for i in range(user_count) if i % team_count == t],
            owners=[f"user-{t}"],
            channels=[
                ChannelRecord(
                    name=f"channel-{t}-{c}",
                    display_name=f"Channel {t}-{c}",
                    is_private=(c % 2 == 1),
                    members=[f"user-{t}"],
                )
                for c in range(channels_per_team)
            ]
        )
        for t in range(team_count)
    ]

    export = TeamsExport(
        users=tuple(users),
        teams=tuple(teams),
        direct_channels=(),
    )

    service = MattermostRecordService(_config(tmp_path))
    records = list(service.iter_user_records(export))

    assert len(records) == user_count
    # Verify correctness of a sample record
    user_t_admin = records[0]["user"]
    assert user_t_admin["username"] == "user-0"
    assert len(user_t_admin["teams"]) == 1
    assert user_t_admin["teams"][0]["name"] == "team-0"
    # user-0 is owner of team-0
    assert user_t_admin["teams"][0]["roles"] == ["team_admin", "team_user"]
