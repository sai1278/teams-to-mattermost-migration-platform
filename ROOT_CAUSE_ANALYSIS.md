# Root Cause Analysis

## Summary

The hardening gap came from three groups of defects:

- Fresh runs reused checkpoint skip logic too early.
- Thread, attachment, and membership preservation was incomplete.
- Password defaults were too permissive for exported artifacts.

## Operational Impact

- CLI runs could emit JSONL without post records.
- Resume logic could silently skip valid work on new output files.
- Threaded replies, direct messages, and attachments were not safe.
- Password fields could be written unless auth mode was set manually.

## Remediation

- Separate fresh-run checkpoint tracking from true resume mode.
- Emit stable post IDs and root IDs for threaded replies.
- Preserve attachments, direct messages, and membership mappings.
- Default password export to empty unless explicitly requested.

## Outcome

The repository now has secure defaults, safer resume behavior, and
fuller coverage for the import pipeline.
