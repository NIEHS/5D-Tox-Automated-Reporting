# Pool Admin — File Pool Management for 5dToxReport

Superuser tool for managing a session's file pool outside the normal UI workflow. Use this when a user asks you to add, remove, or fix files in their study data pool.

## When to use this

- User says "delete the hematology data" or "remove hormones from the pool"
- You manually edited or replaced files in `sessions/{DTXSID}/files/`
- You need to force the pool back to a clean validation-ready state
- You see `[MISSING]` files or stale fingerprints after manual changes

## Commands

### List the pool

See what files exist, grouped by platform. Flags problems.

```bash
uv run python pool_admin.py DTXSID50469320 list
```

Output shows:
- Files grouped by platform name
- `(+sidecar)` — has an associated `.sidecar.json` with per-animal metadata
- `[MISSING]` — fingerprint exists but file is gone from disk (stale)
- `Orphan files` — file on disk but not in fingerprints

### Delete a platform's data

Remove all files for a platform and clean up downstream artifacts.

```bash
uv run python pool_admin.py DTXSID50469320 delete "Hematology"
```

Multiple platforms at once:

```bash
uv run python pool_admin.py DTXSID50469320 delete "Hematology" "Hormones"
```

Preview what would happen without making changes:

```bash
uv run python pool_admin.py DTXSID50469320 delete "Hematology" --dry-run
```

Platform names are **case-insensitive substring matches**:
- `"hemat"` → Hematology
- `"clin"` → Clinical Chemistry AND Clinical (observations)
- `"body"` → Body Weight
- `"organ"` → Organ Weight
- `"tissue"` → Tissue Concentration

Use `--dry-run` first if the match might be ambiguous.

**What gets deleted:**
- Data files (`.txt`, `.csv`, `.xlsx`, `.bm2`) from `files/`
- Associated sidecar files (`.sidecar.json`) from `files/`
- Fingerprint entries from `_fingerprints.json`
- Validation report, precedence decisions, integrated data, animal report
- Processing caches (NTP stats, section cards, genomics, BMD summary)
- BMDS model caches are **kept** (content-hash keyed — unchanged endpoints still hit cache after re-integration)

**What gets marked stale (not deleted):**
- Approved section files (`bm2_*.json`, `genomics_*.json`) — preserves user's narrative edits, shows amber "stale" badge in UI

### Force invalidation (keep files, clear artifacts)

Clear all downstream artifacts without deleting any pool files. Forces re-validation and re-integration from the current file set.

```bash
uv run python pool_admin.py DTXSID50469320 invalidate
```

Use when:
- You edited a file in place (replaced content, same filename)
- Caches seem corrupted or stale
- You want to force a full recompute

## After running any command

**Tell the user to click Validate in the UI.** The script handles disk state only. The Validate button reconciles the server's runtime state:

1. Re-scans `files/` directory — drops stale fingerprints, picks up new files
2. Runs cross-validation on the current file set
3. Updates coverage matrix and section completeness
4. State machine derives the correct phase automatically

## Finding the DTXSID

The DTXSID is the chemical identifier shown in the UI header. It's also the directory name under `sessions/`:

```bash
ls sessions/
# DTXSID50469320  DTXSID70191136  _bm2_cache
```

## Examples

```bash
# User: "hey, can you remove the hematology data? I uploaded the wrong file"
uv run python pool_admin.py DTXSID50469320 delete "Hematology"
# → Tell them to click Validate

# User: "something's wrong with the clinical chemistry numbers"
# You re-export the CSV, replace it in files/, then:
uv run python pool_admin.py DTXSID50469320 invalidate
# → Tell them to click Validate

# Debugging: "what's in this session's pool?"
uv run python pool_admin.py DTXSID50469320 list

# Safety check before deleting:
uv run python pool_admin.py DTXSID50469320 delete "tissue" --dry-run
```
