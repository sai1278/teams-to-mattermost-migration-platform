"""Validated runtime configuration for parser execution."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_DEFAULT_PASSWORD,
    DEFAULT_METRICS_OUTPUT_PATH,
    DEFAULT_OTEL_SERVICE_NAME,
)

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class ParserEnvironmentDefaults(BaseSettings):
    """Environment-driven defaults shared by local scripts and CI."""

    model_config = SettingsConfigDict(env_prefix="TMMP_", extra="ignore")

    anonymize: bool = False
    batch_size: int = DEFAULT_BATCH_SIZE
    default_password: SecretStr = SecretStr(DEFAULT_DEFAULT_PASSWORD)
    fail_on_empty_export: bool = True
    log_level: LogLevel = "INFO"
    metrics_output_path: Path | None = Path(DEFAULT_METRICS_OUTPUT_PATH)
    metrics_pushgateway_url: str | None = None
    otel_service_name: str = DEFAULT_OTEL_SERVICE_NAME
    auth_service: str | None = None
    auth_data_field: str = "email"
    checkpoint_path: Path | None = None
    resume: bool = True


class ParserConfig(BaseModel):
    """Validated runtime configuration for transformation jobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_path: Path
    output_path: Path
    anonymize: bool = False
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=10_000)
    correlation_id: str = Field(default_factory=lambda: uuid4().hex)
    default_password: SecretStr = SecretStr(DEFAULT_DEFAULT_PASSWORD)
    fail_on_empty_export: bool = True
    log_level: LogLevel = "INFO"
    metrics_output_path: Path | None = Path(DEFAULT_METRICS_OUTPUT_PATH)
    metrics_pushgateway_url: str | None = None
    otel_service_name: str = DEFAULT_OTEL_SERVICE_NAME
    auth_service: str | None = None
    auth_data_field: str = "email"
    checkpoint_path: Path | None = None
    resume: bool = True

    @field_validator("input_path")
    @classmethod
    def validate_input_path(cls, value: Path) -> Path:
        if value.suffix.lower() not in {".json"}:
            raise ValueError("input_path must reference a normalized JSON export file")
        return value

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, value: Path) -> Path:
        if value.suffix.lower() != ".jsonl":
            raise ValueError("output_path must end with .jsonl")
        return value

    @field_validator("auth_data_field")
    @classmethod
    def validate_auth_data_field(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"email", "username"}:
            raise ValueError("auth_data_field must be either 'email' or 'username'")
        return normalized

    @classmethod
    def from_inputs(
        cls,
        *,
        input_path: Path,
        output_path: Path,
        anonymize: bool | None = None,
        batch_size: int | None = None,
        correlation_id: str | None = None,
        default_password: str | None = None,
        fail_on_empty_export: bool | None = None,
        log_level: LogLevel | None = None,
        metrics_output_path: Path | None = None,
        metrics_pushgateway_url: str | None = None,
        otel_service_name: str | None = None,
        auth_service: str | None = None,
        auth_data_field: str | None = None,
        checkpoint_path: Path | None = None,
        resume: bool | None = None,
    ) -> ParserConfig:
        defaults = ParserEnvironmentDefaults()
        resolved_output_path = Path(output_path)
        resolved_checkpoint_path = checkpoint_path
        if resolved_checkpoint_path is None:
            resolved_checkpoint_path = resolved_output_path.with_suffix(".checkpoint.json")

        return cls(
            input_path=input_path,
            output_path=resolved_output_path,
            anonymize=defaults.anonymize if anonymize is None else anonymize,
            batch_size=defaults.batch_size if batch_size is None else batch_size,
            correlation_id=correlation_id or uuid4().hex,
            default_password=defaults.default_password
            if default_password is None
            else SecretStr(default_password),
            fail_on_empty_export=defaults.fail_on_empty_export
            if fail_on_empty_export is None
            else fail_on_empty_export,
            log_level=defaults.log_level if log_level is None else log_level,
            metrics_output_path=defaults.metrics_output_path
            if metrics_output_path is None
            else metrics_output_path,
            metrics_pushgateway_url=defaults.metrics_pushgateway_url
            if metrics_pushgateway_url is None
            else metrics_pushgateway_url,
            otel_service_name=defaults.otel_service_name
            if otel_service_name is None
            else otel_service_name,
            auth_service=defaults.auth_service if auth_service is None else auth_service,
            auth_data_field=defaults.auth_data_field
            if auth_data_field is None
            else auth_data_field,
            checkpoint_path=resolved_checkpoint_path,
            resume=defaults.resume if resume is None else resume,
        )

    def ensure_output_parent(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.metrics_output_path is not None:
            self.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.checkpoint_path is not None:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
