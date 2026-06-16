"""Infrastructure adapter for writing JSONL output with bounded buffering."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class JsonlFileWriter:
    """Write JSONL records in batches to reduce syscall overhead.

    Supports optional file splitting for large runs.
    """

    def __init__(
        self,
        output_path: Path,
        *,
        batch_size: int,
        append: bool = False,
        max_chunk_mb: int = 0,
    ):
        self._base_path = output_path
        self._batch_size = batch_size
        self._append = append
        self._max_chunk_mb = max_chunk_mb
        self._buffer: list[str] = []
        self._part_number = 1
        self._current_file_bytes = 0

        # Determine initial path
        if self._max_chunk_mb > 0:
            if append:
                part = 1
                while self._get_part_path(part).exists():
                    part += 1
                if part > 1:
                    self._part_number = part - 1
                else:
                    self._part_number = 1
            else:
                self._part_number = 1
            self._current_path = self._get_part_path(self._part_number)
        else:
            self._current_path = self._base_path

        existing = self._current_path.stat().st_size if self._current_path.exists() else 0
        self._existing_size = existing
        mode = "a" if append else "w"
        self._handle = self._current_path.open(mode, encoding="utf-8")
        self._current_file_bytes = self._existing_size

    def _get_part_path(self, part: int) -> Path:
        suffix = self._base_path.suffix
        stem = self._base_path.stem
        parent = self._base_path.parent
        return parent / f"{stem}.part{part:03d}{suffix}"

    def write_record(self, record: Mapping[str, Any]) -> None:
        self._buffer.append(json.dumps(dict(record), sort_keys=True))
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return

        if self._max_chunk_mb > 0:
            buffer_content = "\n".join(self._buffer) + "\n"
            buffer_bytes = len(buffer_content.encode("utf-8"))

            max_bytes = self._max_chunk_mb * 1024 * 1024
            if (
                self._current_file_bytes > 0
                and self._current_file_bytes + buffer_bytes > max_bytes
            ):
                self._handle.close()
                self._part_number += 1
                self._current_path = self._get_part_path(self._part_number)
                self._handle = self._current_path.open("w", encoding="utf-8")
                # Write version record immediately to the new chunk!
                version_record = {"type": "version", "version": 1}
                version_line = json.dumps(version_record, sort_keys=True) + "\n"
                self._handle.write(version_line)
                self._current_file_bytes = len(version_line.encode("utf-8"))

        buffer_content = "\n".join(self._buffer) + "\n"
        self._handle.write(buffer_content)
        self._handle.flush()
        self._current_file_bytes += len(buffer_content.encode("utf-8"))
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
