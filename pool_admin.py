#!/usr/bin/env python3
"""
pool_admin.py — Superuser tool for managing the file pool behind the scenes.

Use this when a user asks you to remove files from their pool, or when you
need to manually adjust the pool composition outside the normal UI workflow.

After running this script, the user clicks Validate in the UI to reconcile
the state.  The validation re-scans the files/ directory, drops stale
fingerprints, and the state machine derives the correct phase.

Usage:
    # List files in a session's pool, grouped by platform:
    python pool_admin.py DTXSID50469320 list

    # Delete all files for a platform (data files + sidecars):
    python pool_admin.py DTXSID50469320 delete "Hematology"

    # Delete files for multiple platforms:
    python pool_admin.py DTXSID50469320 delete "Hematology" "Hormones"

    # Show what would be deleted (dry run):
    python pool_admin.py DTXSID50469320 delete "Hematology" --dry-run

    # Reset the pool to a clean state (delete all downstream artifacts,
    # keep files):
    python pool_admin.py DTXSID50469320 invalidate

Platform names are matched case-insensitively against the fingerprints file.
Partial matches work: "hemat" matches "Hematology", "clin" matches both
"Clinical Chemistry" and "Clinical" (clinical observations).

The script:
  1. Finds files belonging to the target platform(s) via _fingerprints.json
  2. Deletes the data files (.txt, .csv, .xlsx, .bm2) from files/
  3. Deletes associated sidecar files (.sidecar.json) from files/
  4. Removes the entries from _fingerprints.json
  5. Deletes downstream artifacts (validation_report.json, precedence.json,
     integrated.json, _category_lookup.json, animal_report.json)
  6. Deletes processing caches (_cache_ntp_*, _cache_sections_*,
     _cache_genomics_*, _cache_bmd_summary_* — keeps _cache_bmds_*)
  7. Marks approved sections (bm2_*.json, genomics_*.json) as stale
"""

import argparse
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants — artifacts to clean up after pool mutation
# ---------------------------------------------------------------------------

# Downstream artifacts that become stale when the file pool changes.
# These are deleted unconditionally on any pool mutation.
DOWNSTREAM_ARTIFACTS = [
    "validation_report.json",
    "precedence.json",
    "integrated.json",
    "_category_lookup.json",
    "animal_report.json",
]

# Cache file prefixes to delete.  BMDS caches are content-hash keyed
# and survive re-integration (unchanged endpoints still hit cache),
# so we keep them.
CACHE_PREFIXES_TO_DELETE = [
    "_cache_ntp_",
    "_cache_sections_",
    "_cache_genomics_",
    "_cache_bmd_summary_",
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def find_session_dir(dtxsid: str) -> Path:
    """Locate the session directory for a DTXSID.

    Searches the standard location: sessions/{dtxsid}/ relative to this
    script's directory (which is the project root).
    """
    # Try relative to script location first, then cwd
    for base in [Path(__file__).parent, Path.cwd()]:
        d = base / "sessions" / dtxsid
        if d.exists():
            return d
    print(f"ERROR: Session directory not found for {dtxsid}", file=sys.stderr)
    sys.exit(1)


def load_fingerprints(session_dir: Path) -> dict:
    """Load the fingerprints file, returning {filename: fingerprint_dict}."""
    fp_path = session_dir / "_fingerprints.json"
    if not fp_path.exists():
        return {}
    return json.loads(fp_path.read_text(encoding="utf-8"))


def save_fingerprints(session_dir: Path, fingerprints: dict) -> None:
    """Write the fingerprints file back to disk."""
    fp_path = session_dir / "_fingerprints.json"
    fp_path.write_text(
        json.dumps(fingerprints, indent=2, default=str),
        encoding="utf-8",
    )


def find_files_for_platforms(
    session_dir: Path,
    fingerprints: dict,
    platform_queries: list[str],
) -> tuple[list[str], list[Path]]:
    """Find filenames and paths matching the given platform queries.

    Platform queries are matched case-insensitively as substrings, so
    "hemat" matches "Hematology" and "clin" matches "Clinical Chemistry"
    and "Clinical".

    Returns:
        (matched_filenames, matched_paths) — filenames from fingerprints
        and full paths including sidecar files.
    """
    files_dir = session_dir / "files"
    matched_filenames = []
    matched_paths = []

    # Normalize queries to lowercase for case-insensitive matching
    queries_lower = [q.lower() for q in platform_queries]

    for filename, fp_data in fingerprints.items():
        platform = (fp_data.get("platform") or "").lower()
        if any(q in platform for q in queries_lower):
            matched_filenames.append(filename)
            # The data file itself
            data_path = files_dir / filename
            if data_path.exists():
                matched_paths.append(data_path)
            # Associated sidecar file (same stem + .sidecar.json)
            stem = Path(filename).stem
            sidecar = files_dir / f"{stem}.sidecar.json"
            if sidecar.exists():
                matched_paths.append(sidecar)

    return matched_filenames, matched_paths


def invalidate_downstream(session_dir: Path, dry_run: bool = False) -> list[str]:
    """Delete downstream artifacts and caches, mark approved sections stale.

    This is the same logic as invalidate_pool_artifacts() in
    pool_orchestrator.py, but runs standalone without the server.

    Returns list of actions taken (for logging).
    """
    actions = []

    # Delete downstream artifacts
    for name in DOWNSTREAM_ARTIFACTS:
        p = session_dir / name
        if p.exists():
            if not dry_run:
                p.unlink()
            actions.append(f"{'Would delete' if dry_run else 'Deleted'}: {name}")

    # Delete processing caches (keep BMDS caches)
    for cache_file in sorted(session_dir.glob("_cache_*.json")):
        if any(cache_file.name.startswith(prefix) for prefix in CACHE_PREFIXES_TO_DELETE):
            if not dry_run:
                cache_file.unlink()
            actions.append(f"{'Would delete' if dry_run else 'Deleted'}: {cache_file.name}")

    # Mark approved sections as stale
    for pattern in ("bm2_*.json", "genomics_*.json"):
        for section_file in sorted(session_dir.glob(pattern)):
            try:
                data = json.loads(section_file.read_text(encoding="utf-8"))
                if not data.get("stale"):
                    if not dry_run:
                        data["stale"] = True
                        section_file.write_text(
                            json.dumps(data, indent=2, default=str),
                            encoding="utf-8",
                        )
                    actions.append(
                        f"{'Would mark' if dry_run else 'Marked'} stale: {section_file.name}"
                    )
            except Exception as e:
                actions.append(f"WARNING: Could not process {section_file.name}: {e}")

    return actions


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(session_dir: Path) -> None:
    """List all files in the pool, grouped by platform."""
    fingerprints = load_fingerprints(session_dir)
    files_dir = session_dir / "files"

    if not fingerprints:
        print("No fingerprints found.  Pool may be empty or not yet validated.")
        # Still list raw files
        if files_dir.exists():
            raw_files = sorted(f.name for f in files_dir.iterdir() if f.is_file())
            if raw_files:
                print(f"\nRaw files in {files_dir}/ ({len(raw_files)}):")
                for f in raw_files:
                    print(f"  {f}")
        return

    # Group by platform
    by_platform: dict[str, list[str]] = {}
    for filename, fp_data in fingerprints.items():
        platform = fp_data.get("platform") or "(unknown)"
        by_platform.setdefault(platform, []).append(filename)

    print(f"Pool files for {session_dir.name}:\n")
    for platform in sorted(by_platform.keys()):
        filenames = sorted(by_platform[platform])
        print(f"  {platform}:")
        for fn in filenames:
            # Check if file actually exists on disk
            exists = (files_dir / fn).exists()
            status = "" if exists else "  [MISSING]"
            # Check for sidecar
            stem = Path(fn).stem
            has_sidecar = (files_dir / f"{stem}.sidecar.json").exists()
            sidecar_note = " (+sidecar)" if has_sidecar else ""
            print(f"    {fn}{sidecar_note}{status}")
        print()

    # Check for files on disk not in fingerprints
    if files_dir.exists():
        fingerprinted = set(fingerprints.keys())
        # Also include sidecar filenames as "accounted for"
        for fn in fingerprinted:
            stem = Path(fn).stem
        orphans = []
        for f in sorted(files_dir.iterdir()):
            if f.is_file() and f.name not in fingerprinted and not f.name.endswith(".sidecar.json"):
                orphans.append(f.name)
        if orphans:
            print("  Orphan files (not in fingerprints):")
            for fn in orphans:
                print(f"    {fn}")
            print()


def cmd_delete(
    session_dir: Path,
    platform_queries: list[str],
    dry_run: bool = False,
) -> None:
    """Delete all files for the given platform(s) and invalidate downstream."""
    fingerprints = load_fingerprints(session_dir)

    if not fingerprints:
        print("No fingerprints found.  Nothing to delete.")
        return

    matched_filenames, matched_paths = find_files_for_platforms(
        session_dir, fingerprints, platform_queries,
    )

    if not matched_filenames and not matched_paths:
        print(f"No files found matching: {', '.join(platform_queries)}")
        print("\nAvailable platforms:")
        platforms = sorted(set(
            fp.get("platform", "(unknown)") for fp in fingerprints.values()
        ))
        for p in platforms:
            print(f"  {p}")
        return

    # Show what will be deleted
    print(f"{'DRY RUN — ' if dry_run else ''}Deleting files for: {', '.join(platform_queries)}\n")

    print("Data files to remove from fingerprints:")
    for fn in sorted(matched_filenames):
        print(f"  {fn}")

    print("\nFiles to delete from disk:")
    for p in sorted(matched_paths):
        print(f"  {p.name}")

    # Delete files from disk
    if not dry_run:
        for p in matched_paths:
            p.unlink()
            print(f"  Deleted: {p.name}")

    # Remove from fingerprints
    new_fingerprints = {
        fn: fp for fn, fp in fingerprints.items()
        if fn not in matched_filenames
    }
    if not dry_run:
        save_fingerprints(session_dir, new_fingerprints)
    remaining = len(new_fingerprints)
    print(f"\nFingerprints: {len(fingerprints)} → {remaining}"
          f" ({'would remove' if dry_run else 'removed'} {len(fingerprints) - remaining})")

    # Invalidate downstream artifacts
    print("\nDownstream cleanup:")
    actions = invalidate_downstream(session_dir, dry_run=dry_run)
    for action in actions:
        print(f"  {action}")

    if not dry_run:
        print(f"\nDone.  Tell the user to click Validate to reconcile the pool state.")
    else:
        print(f"\nDry run complete.  No files were changed.")


def cmd_invalidate(session_dir: Path, dry_run: bool = False) -> None:
    """Invalidate all downstream artifacts without deleting any pool files.

    Useful when you've manually edited files or need to force re-validation
    and re-integration from the existing file set.
    """
    print(f"{'DRY RUN — ' if dry_run else ''}Invalidating downstream artifacts for {session_dir.name}\n")

    actions = invalidate_downstream(session_dir, dry_run=dry_run)
    for action in actions:
        print(f"  {action}")

    if not actions:
        print("  Nothing to invalidate.")

    if not dry_run:
        print(f"\nDone.  Tell the user to click Validate to reconcile the pool state.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Superuser tool for managing the 5dToxReport file pool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s DTXSID50469320 list
  %(prog)s DTXSID50469320 delete "Hematology"
  %(prog)s DTXSID50469320 delete "Hematology" "Hormones" --dry-run
  %(prog)s DTXSID50469320 invalidate
        """,
    )
    parser.add_argument("dtxsid", help="DTXSID identifying the session")
    parser.add_argument(
        "command",
        choices=["list", "delete", "invalidate"],
        help="Action to perform",
    )
    parser.add_argument(
        "platforms",
        nargs="*",
        help="Platform name(s) to delete (case-insensitive substring match)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()
    session_dir = find_session_dir(args.dtxsid)

    if args.command == "list":
        cmd_list(session_dir)
    elif args.command == "delete":
        if not args.platforms:
            parser.error("delete requires at least one platform name")
        cmd_delete(session_dir, args.platforms, dry_run=args.dry_run)
    elif args.command == "invalidate":
        cmd_invalidate(session_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
