"""Prometheus-compatible metrics for parser runs."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, push_to_gateway
from prometheus_client.exposition import write_to_textfile

from ..config import ParserConfig


class ParserMetrics:
    """Capture throughput, latency, and outcome metrics for parser executions."""

    def __init__(self, config: ParserConfig):
        self._config = config
        self._registry = CollectorRegistry()
        self._runs_total = Counter(
            "tmmp_parser_runs_total",
            "Total parser runs grouped by status.",
            labelnames=("status",),
            registry=self._registry,
        )
        self._records_total = Counter(
            "tmmp_parser_records_emitted_total",
            "Total emitted Mattermost records grouped by record type.",
            labelnames=("record_type",),
            registry=self._registry,
        )
        self._stage_duration_seconds = Histogram(
            "tmmp_parser_stage_duration_seconds",
            "Duration spent in major parser stages.",
            labelnames=("stage",),
            registry=self._registry,
        )
        self._input_bytes_total = Gauge(
            "tmmp_parser_input_bytes",
            "Size of the input export processed by the parser.",
            registry=self._registry,
        )
        self._throughput = Gauge(
            "tmmp_parser_records_per_second",
            "Observed parser throughput for the latest successful run.",
            registry=self._registry,
        )
        self._last_run_records_total = Gauge(
            "tmmp_parser_last_run_records_total",
            "Number of records emitted during the latest successful run.",
            registry=self._registry,
        )
        self._failures_total = Counter(
            "tmmp_parser_failures_total",
            "Total parser failures grouped by error type.",
            labelnames=("error_type",),
            registry=self._registry,
        )
        self._attachments_total = Counter(
            "tmmp_parser_attachments_processed_total",
            "Total processed attachments grouped by status.",
            labelnames=("status",),
            registry=self._registry,
        )
        self._checkpoint_resumes_total = Counter(
            "tmmp_parser_checkpoint_resumes_total",
            "Total times the parser resumed execution from a checkpoint.",
            registry=self._registry,
        )

    def observe_input_bytes(self, input_bytes: int) -> None:
        self._input_bytes_total.set(input_bytes)

    def observe_record(self, record_type: str) -> None:
        self._records_total.labels(record_type=record_type).inc()

    def observe_stage_duration(self, stage_name: str, duration_seconds: float) -> None:
        self._stage_duration_seconds.labels(stage=stage_name).observe(duration_seconds)

    def mark_success(self, *, records_written: int, duration_seconds: float) -> None:
        self._runs_total.labels(status="success").inc()
        self._last_run_records_total.set(records_written)
        if duration_seconds > 0:
            self._throughput.set(records_written / duration_seconds)

    def mark_failure(self, error_type: str) -> None:
        self._runs_total.labels(status="failed").inc()
        self._failures_total.labels(error_type=error_type).inc()

    def observe_attachment(self, status: str) -> None:
        self._attachments_total.labels(status=status).inc()

    def observe_checkpoint_resume(self) -> None:
        self._checkpoint_resumes_total.inc()

    def publish(self) -> None:
        metrics_path = self._config.metrics_output_path
        if metrics_path is not None:
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            write_to_textfile(str(metrics_path), self._registry)

        if self._config.metrics_pushgateway_url:
            push_to_gateway(
                self._config.metrics_pushgateway_url,
                job="teams-mattermost-parser",
                registry=self._registry,
                grouping_key={"correlation_id": self._config.correlation_id},
            )
