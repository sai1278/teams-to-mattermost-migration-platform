"""Typed domain models for the normalized Teams export contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ImmutableModel(BaseModel):
    """Base model used by frozen domain objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PostRecord(ImmutableModel):
    username: str
    message: str
    timestamp_ms: int = Field(ge=0)


class ChannelRecord(ImmutableModel):
    name: str
    display_name: str
    is_private: bool = False
    posts: tuple[PostRecord, ...] = ()


class TeamRecord(ImmutableModel):
    name: str
    display_name: str
    description: str = ""
    channels: tuple[ChannelRecord, ...] = ()


class UserRecord(ImmutableModel):
    username: str
    email: EmailStr
    nickname: str
    teams: tuple[str, ...] = ()


class TeamsExport(ImmutableModel):
    teams: tuple[TeamRecord, ...]
    users: tuple[UserRecord, ...]
