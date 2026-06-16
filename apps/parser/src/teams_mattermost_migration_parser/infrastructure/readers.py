"""Infrastructure adapter for streaming normalized Teams export files."""

from __future__ import annotations

import json
from collections.abc import Iterator
from os import PathLike
from pathlib import Path
from typing import TypeVar

import ijson
from pydantic import BaseModel, ValidationError

from ..domain.exceptions import InputValidationError, SourceReadError
from ..domain.models import DirectChannelRecord, TeamRecord, TeamsExport, UserRecord

ModelT = TypeVar("ModelT", bound=BaseModel)


class TeamsExportFileGateway:
    """Read normalized export data with low memory overhead via a single-pass streaming parser."""

    def __init__(self, input_path: str | PathLike[str] | Path):
        self._input_path = Path(input_path)
        self._parsed = False
        self._users: list[UserRecord] = []
        self._teams: list[TeamRecord] = []
        self._direct_channels: list[DirectChannelRecord] = []

    def _parse_if_needed(self) -> None:
        if self._parsed:
            return

        if not self._input_path.exists():
            raise SourceReadError(f"input file does not exist: {self._input_path}")

        try:
            with self._input_path.open("rb") as handle:
                parser = ijson.parse(handle)
                builder = None
                current_prefix = None
                for prefix, event, value in parser:
                    # Validate schema version
                    if (
                        prefix in ("schema_version", "version")
                        and event in ("number", "string", "boolean", "null")
                        and value is not None
                        and str(value) != "1"
                    ):
                        raise InputValidationError(
                            f"Unsupported schema version: {value}. Expected: 1"
                        )

                    # Check for items
                    if prefix in ("users.item", "teams.item", "direct_channels.item"):
                        if event == "start_map":
                            builder = ijson.ObjectBuilder()
                            current_prefix = prefix
                        if builder is not None:
                            builder.event(event, value)
                        if event == "end_map" and builder is not None:
                            obj = builder.value
                            builder = None
                            try:
                                if current_prefix == "users.item":
                                    self._users.append(UserRecord.model_validate(obj))
                                elif current_prefix == "teams.item":
                                    self._teams.append(TeamRecord.model_validate(obj))
                                elif current_prefix == "direct_channels.item":
                                    self._direct_channels.append(
                                        DirectChannelRecord.model_validate(obj)
                                    )
                            except ValidationError as exc:
                                raise InputValidationError(
                                    f"invalid object in '{current_prefix}': {exc}"
                                ) from exc
                    elif builder is not None:
                        builder.event(event, value)
        except ValidationError as exc:
            raise InputValidationError(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise SourceReadError(f"input file is not valid JSON: {self._input_path}") from exc
        except OSError as exc:
            raise SourceReadError(f"failed to open input file: {self._input_path}") from exc
        except ijson.JSONError as exc:
            raise SourceReadError(f"failed to stream parse input file: {self._input_path}") from exc

        self._parsed = True

    def iter_teams(self) -> Iterator[TeamRecord]:
        self._parse_if_needed()
        yield from self._teams

    def iter_users(self) -> Iterator[UserRecord]:
        self._parse_if_needed()
        yield from self._users

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        self._parse_if_needed()
        yield from self._direct_channels

    def input_size_bytes(self) -> int:
        try:
            return self._input_path.stat().st_size
        except OSError as exc:
            raise SourceReadError(f"could not stat input file: {self._input_path}") from exc

    def materialize(self) -> TeamsExport:
        self._parse_if_needed()
        return TeamsExport(
            teams=tuple(self._teams),
            users=tuple(self._users),
            direct_channels=tuple(self._direct_channels),
        )

    def validate_schema_version(self) -> None:
        """Fail-fast if the export declares an unsupported schema version."""
        self._parse_if_needed()

