"""Infrastructure adapter for streaming normalized Teams export files."""

from __future__ import annotations

import json
from collections.abc import Iterator
from os import PathLike
from pathlib import Path
from typing import Any, TypeVar

import ijson
from pydantic import BaseModel, ValidationError

from ..domain.exceptions import InputValidationError, SourceReadError
from ..domain.models import DirectChannelRecord, TeamRecord, TeamsExport, UserRecord

ModelT = TypeVar("ModelT", bound=BaseModel)


class TeamsExportFileGateway:
    """Read normalized export data with low memory overhead via repeated streaming passes."""

    def __init__(self, input_path: str | PathLike[str] | Path):
        self._input_path = Path(input_path)

    def iter_teams(self) -> Iterator[TeamRecord]:
        yield from self._iter_items("teams.item", TeamRecord)

    def iter_users(self) -> Iterator[UserRecord]:
        yield from self._iter_items("users.item", UserRecord)

    def iter_direct_channels(self) -> Iterator[DirectChannelRecord]:
        yield from self._iter_items("direct_channels.item", DirectChannelRecord)

    def input_size_bytes(self) -> int:
        try:
            return self._input_path.stat().st_size
        except OSError as exc:
            raise SourceReadError(f"could not stat input file: {self._input_path}") from exc

    def materialize(self) -> TeamsExport:
        return TeamsExport(
            teams=tuple(self.iter_teams()),
            users=tuple(self.iter_users()),
            direct_channels=tuple(self.iter_direct_channels()),
        )

    def _iter_items(self, prefix: str, model_class: type[ModelT]) -> Iterator[ModelT]:
        if not self._input_path.exists():
            raise SourceReadError(f"input file does not exist: {self._input_path}")

        try:
            with self._input_path.open("rb") as handle:
                for item in ijson.items(handle, prefix):
                    yield self._validate_item(prefix=prefix, item=item, model_class=model_class)
        except ValidationError as exc:
            raise InputValidationError(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise SourceReadError(f"input file is not valid JSON: {self._input_path}") from exc
        except OSError as exc:
            raise SourceReadError(f"failed to open input file: {self._input_path}") from exc
        except ijson.JSONError as exc:
            raise SourceReadError(f"failed to stream parse input file: {self._input_path}") from exc

    @staticmethod
    def _validate_item(*, prefix: str, item: Any, model_class: type[ModelT]) -> ModelT:
        try:
            return model_class.model_validate(item)
        except ValidationError as exc:
            raise InputValidationError(f"invalid object in '{prefix}': {exc}") from exc
