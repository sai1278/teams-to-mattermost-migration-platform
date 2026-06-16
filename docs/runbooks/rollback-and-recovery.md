# Rollback and Operational Recovery Procedures

This runbook outlines SRE procedures for rollback and recovery in case of failures or corrupt state during Teams → Mattermost migrations.

## 1. Migration Rollback Procedure

If a migration run fails midway or loads corrupt/incorrect data, perform a rollback by cleaning up the target Mattermost database or removing the imported items.

### Step 1.1: Identify Teams and Channels to Rollback
Identify the names of the teams and channels written in the import JSONL files. 
You can extract them using:
```bash
grep '"type": "team"' import.jsonl | jq '.team.name'
grep '"type": "channel"' import.jsonl | jq '.channel.name'
```

### Step 1.2: Remove Imported Teams
If using Mattermost command line (`mattermost` or `mmctl` CLI), you can permanently delete the migrated teams.
Run this command on the Mattermost application server or inside the container:
```bash
# Permenantly delete team and all its channels/contents
mattermost team delete <team-slug> --confirm
```
Or using `mmctl`:
```bash
mmctl team delete <team-slug> --confirm
```

### Step 1.3: Clean Up Users
If users were incorrectly created, they can be deactivated. Note that Mattermost does not support hard-deleting users to preserve audit trails, but they can be deactivated:
```bash
mmctl user deactivate <username>
```

---

## 2. Checkpoint Recovery Procedures

If the parser halts due to an OOM or Node crash, the checkpoint file might be corrupt. However, because of atomic checkpointing (`temp-file + fsync + replace`), the active checkpoint is guaranteed to be valid and uncorrupted.

### Procedure to Resume:
1. Simply relaunch the parser command with the `--resume` flag.
2. The parser will read the checkpoint file, identify the completed teams, channels, and users, and skip them.
3. For the last processed posts sharing the identical boundary timestamp, the parser will filter them out by ID to prevent duplicates.

### Procedure to Force Restart:
If you wish to discard the checkpoint and start fresh, delete the checkpoint file:
```bash
rm -f <output_path>.checkpoint.json
```
Then run the command without `--resume` or with `--no-resume`.
