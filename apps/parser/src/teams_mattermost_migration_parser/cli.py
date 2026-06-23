"""Command line entry point for the parser app."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import ParserConfig, ParserEnvironmentDefaults
from .container import build_pipeline
from .observability import configure_logging, set_correlation_id, setup_telemetry

LOGGER = logging.getLogger("teams_mattermost_migration_parser")


def build_parser(defaults: ParserEnvironmentDefaults) -> argparse.ArgumentParser:
    """Build the CLI parser using environment-derived defaults."""

    parser = argparse.ArgumentParser(
        description="Transform a normalized Teams export into Mattermost JSONL."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the normalized Teams export JSON file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination JSONL file.",
    )
    parser.add_argument(
        "--anonymize",
        action="store_true",
        default=defaults.anonymize,
        help="Replace usernames, email addresses, and sensitive message text.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=defaults.batch_size,
        help="Number of JSONL records to buffer before flushing to disk.",
    )
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="Optional correlation ID used in logs and pushed metrics.",
    )
    parser.add_argument(
        "--fail-on-empty-export",
        action=argparse.BooleanOptionalAction,
        default=defaults.fail_on_empty_export,
        help="Fail fast when the input export has no teams or users.",
    )
    parser.add_argument(
        "--log-level",
        default=defaults.log_level,
        help="Python log level.",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=defaults.metrics_output_path,
        help="Optional Prometheus textfile output path.",
    )
    parser.add_argument(
        "--metrics-pushgateway-url",
        default=defaults.metrics_pushgateway_url,
        help="Optional Pushgateway URL used to publish parser metrics.",
    )
    parser.add_argument(
        "--otel-service-name",
        default=defaults.otel_service_name,
        help="Service name used in structured logs and future OTEL exporters.",
    )
    parser.add_argument(
        "--auth-service",
        default=defaults.auth_service,
        help="SSO authentication service (e.g. saml, gitlab).",
    )
    parser.add_argument(
        "--auth-data-field",
        default=defaults.auth_data_field,
        help="Field to use for SSO auth_data (email or username).",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=defaults.checkpoint_path,
        help="State file path for resuming migrations.",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=defaults.resume,
        help="Resume migration from checkpoint if file exists.",
    )
    parser.add_argument(
        "--max-chunk-mb",
        type=int,
        default=defaults.max_chunk_mb,
        help="Maximum size of each JSONL chunk in MB. 0 means disabled.",
    )
    parser.add_argument(
        "--attachment-workers",
        type=int,
        default=defaults.attachment_workers,
        help="Number of concurrent worker threads for downloading attachments.",
    )
    parser.add_argument(
        "--ms-graph-tenant-id",
        default=defaults.ms_graph_tenant_id,
        help="Microsoft Graph Tenant ID.",
    )
    parser.add_argument(
        "--ms-graph-client-id",
        default=defaults.ms_graph_client_id,
        help="Microsoft Graph Client ID.",
    )
    parser.add_argument(
        "--ms-graph-client-secret",
        default=None,
        help="Microsoft Graph Client Secret.",
    )
    return parser


def main() -> int:
    """Run the CLI transformation workflow."""

    defaults = ParserEnvironmentDefaults()
    args = build_parser(defaults).parse_args()
    config = ParserConfig.from_inputs(
        anonymize=args.anonymize,
        batch_size=args.batch_size,
        correlation_id=args.correlation_id,
        fail_on_empty_export=args.fail_on_empty_export,
        input_path=args.input,
        log_level=args.log_level,
        metrics_output_path=args.metrics_output,
        metrics_pushgateway_url=args.metrics_pushgateway_url,
        otel_service_name=args.otel_service_name,
        output_path=args.output,
        auth_service=args.auth_service,
        auth_data_field=args.auth_data_field,
        checkpoint_path=args.checkpoint_path,
        resume=args.resume,
        max_chunk_mb=args.max_chunk_mb,
        attachment_workers=args.attachment_workers,
        ms_graph_tenant_id=args.ms_graph_tenant_id,
        ms_graph_client_id=args.ms_graph_client_id,
        ms_graph_client_secret=args.ms_graph_client_secret,
    )
    config.ensure_output_parent()

    set_correlation_id(config.correlation_id)
    configure_logging(config.log_level, service_name=config.otel_service_name)
    setup_telemetry(config.otel_service_name)

    result = build_pipeline(config).run()
    LOGGER.info(
        "transformation completed",
        extra={
            "event": "transformation_completed",
            "details": {
                "records_written": result.records_written,
                "teams": result.teams,
                "channels": result.channels,
                "users": result.users,
                "posts": result.posts,
                "input_path": str(config.input_path),
                "output_path": str(config.output_path),
                "metrics_output_path": str(config.metrics_output_path)
                if config.metrics_output_path is not None
                else None,
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
