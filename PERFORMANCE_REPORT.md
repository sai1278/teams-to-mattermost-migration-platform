# Performance Report

## Design Choices

- The export reader streams via `ijson` instead of loading the full file.
- JSONL writing uses bounded buffering to reduce syscall overhead.
- Attachment processing retries with backoff instead of blocking forever.
- Metrics record throughput, stage duration, and processed bytes.

## Observed Behavior

- Full test execution completed quickly in this environment.
- The parser handled sample exports without memory-heavy materialization.
- Resume logic can continue from prior progress without reprocessing.

## Tuning Guidance

- Increase `batch_size` for large imports when memory allows.
- Prefer streaming exports and object storage for large attachment sets.
- Use the metrics output path or Pushgateway for run visibility.
