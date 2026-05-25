# Data Flow

## Input contract

The parser currently consumes a normalized JSON export contract stored in
`tests/fixtures/sample-teams-export.json`. That fixture represents the shape an
upstream extractor or adapter should emit.

Top-level objects:

- `users`
- `teams`
- `teams[].channels`
- `teams[].channels[].posts`

## Transformation stages

1. Load the normalized export document.
2. Validate team, channel, and user references before any import is attempted.
3. Render Mattermost bulk import records in JSONL order:
   - version
   - teams
   - channels
   - users
   - posts
4. Write the payload to `artifacts/imports/`.
5. Validate the payload with the Mattermost CLI before applying it.

## Scale-out path

When the project moves beyond local fixtures, the same flow can be extended with:

- object storage for large imports
- Redis-backed work coordination
- queue-driven parser workers
- sharded or batched JSONL generation
- Kubernetes Jobs for large migration waves
