"""Typed domain models for the normalized Teams export contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ImmutableModel(BaseModel):
    """Base model used by frozen domain objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AttachmentRecord(ImmutableModel):
    name: str
    path: str
    url: str | None = None


class PostRecord(ImmutableModel):
    username: str
    message: str
    timestamp_ms: int = Field(ge=0)
    id: str | None = None
    parent_id: str | None = None
    attachments: tuple[AttachmentRecord, ...] = ()


class ChannelRecord(ImmutableModel):
    name: str
    display_name: str
    is_private: bool = False
    posts: tuple[PostRecord, ...] = ()
    members: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()


class TeamRecord(ImmutableModel):
    name: str
    display_name: str
    description: str = ""
    channels: tuple[ChannelRecord, ...] = ()
    members: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()


class UserRecord(ImmutableModel):
    username: str
    email: EmailStr
    nickname: str
    teams: tuple[str, ...] = ()


class DirectChannelRecord(ImmutableModel):
    members: tuple[str, ...]
    posts: tuple[PostRecord, ...] = ()


class TeamsExport(ImmutableModel):
    teams: tuple[TeamRecord, ...]
    users: tuple[UserRecord, ...]
    direct_channels: tuple[DirectChannelRecord, ...] = ()
