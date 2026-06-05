"""Infrastructure adapter for writing JSONL output with bounded buffering."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class JsonlFileWriter:
    """Write JSONL records in batches to reduce syscall overhead on large runs."""

    def __init__(self, output_path: Path, *, batch_size: int, append: bool = False):
        self._output_path = output_path
        self._batch_size = batch_size
        self._buffer: list[str] = []
        self._existing_size = output_path.stat().st_size if output_path.exists() else 0
        self._append = append
        mode = "a" if append else "w"
        self._handle = self._output_path.open(mode, encoding="utf-8")

    def write_record(self, record: Mapping[str, Any]) -> None:
        self._buffer.append(json.dumps(dict(record), sort_keys=True))
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self._handle.write("\n".join(self._buffer))
        self._handle.write("\n")
        self._handle.flush()
        self._buffer.clear()

    def close(self) -> None:
        self.flush()
        self._handle.close()

    @property
    def has_existing_content(self) -> bool:
        return self._existing_size > 0

    @property
    def append_mode(self) -> bool:
        return self._append
