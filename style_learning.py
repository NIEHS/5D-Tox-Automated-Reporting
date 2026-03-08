"""
style_learning.py — Writing style profile persistence and LLM-based extraction.

Manages a global style profile (sessions/_style_profile.json) that captures
writing preferences learned from comparing LLM-generated text to user edits.
The profile is chemical-agnostic — writing style transcends individual reports.

The extraction pipeline:
  1. User edits LLM-generated text and approves it
  2. _extract_and_merge_style_rules() compares original vs. edited text
  3. Claude Haiku identifies deliberate style changes (terminology, grammar, etc.)
  4. New rules are merged into the profile, reinforcing existing ones or adding new
  5. Future LLM calls include the profile as system-prompt context

Profile layout:
  sessions/_style_profile.json
    {
      "version": 1,
      "updated_at": "...",
      "rules": [
        {"rule": "...", "category": "terminology", "confidence": 3, ...},
        ...
      ]
    }
"""

import json
import logging
import traceback

from session_store import SESSIONS_DIR, now_iso
from llm_helpers import llm_generate_json


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the global style profile file — lives alongside session dirs.
STYLE_PROFILE_PATH = SESSIONS_DIR / "_style_profile.json"

# Maximum number of style rules to retain — when full, the lowest-confidence
# rule is evicted to make room for new ones.
MAX_STYLE_RULES = 30

# Valid categories for style rules — used for validation when merging.
# Rules with unrecognized categories default to "phrasing".
STYLE_CATEGORIES = {
    "terminology", "grammar", "phrasing", "structure", "formatting", "tone",
}


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_style_profile() -> dict:
    """
    Load the global style profile from disk, returning an empty structure if
    the file doesn't exist yet.

    The profile has three top-level keys:
      - version (int): schema version for future migrations
      - updated_at (str): ISO 8601 timestamp of last modification
      - rules (list[dict]): ordered list of learned style rules, each with:
          rule (str), category (str), confidence (int), first_seen, last_seen
    """
    if STYLE_PROFILE_PATH.exists():
        try:
            return json.loads(STYLE_PROFILE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupted file — start fresh rather than crash
            pass
    return {"version": 1, "updated_at": now_iso(), "rules": []}


def save_style_profile(profile: dict) -> None:
    """
    Write the style profile to disk.  Creates the sessions/ directory if
    needed (same dir used for per-chemical session storage).
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    profile["updated_at"] = now_iso()
    STYLE_PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, default=str), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def merge_rules(profile: dict, new_rules: list[dict]) -> dict:
    """
    Merge newly-extracted style rules into the existing profile.

    For each new rule:
      - If it matches an existing rule (exact string match on the 'rule' key),
        increment the existing rule's confidence and update last_seen.
      - If it's genuinely new, add it with confidence=1.
      - If adding pushes the total past MAX_STYLE_RULES, evict the rule with
        the lowest confidence (oldest last_seen breaks ties).

    The LLM extraction prompt is given the existing rules to avoid semantic
    duplicates, so exact-match dedup here is a safety net — most real dedup
    happens at extraction time.

    Returns the modified profile (also mutates in place for convenience).
    """
    existing_rules = profile.get("rules", [])
    now = now_iso()

    for nr in new_rules:
        rule_text = nr.get("rule", "").strip()
        category = nr.get("category", "phrasing").strip().lower()
        if not rule_text:
            continue
        # Default to "phrasing" if the LLM returns an unknown category
        if category not in STYLE_CATEGORIES:
            category = "phrasing"

        # Check for exact duplicate by rule text
        matched = False
        for er in existing_rules:
            if er["rule"].strip().lower() == rule_text.lower():
                # Reinforce: bump confidence and update timestamp
                er["confidence"] = er.get("confidence", 1) + 1
                er["last_seen"] = now
                matched = True
                break

        if not matched:
            existing_rules.append({
                "rule": rule_text,
                "category": category,
                "confidence": 1,
                "first_seen": now,
                "last_seen": now,
            })

    # Evict lowest-confidence rules if over the cap.
    # Sort by confidence ascending, then by last_seen ascending (oldest first)
    # so we drop the least-reinforced, least-recently-seen rules.
    if len(existing_rules) > MAX_STYLE_RULES:
        existing_rules.sort(
            key=lambda r: (r.get("confidence", 1), r.get("last_seen", "")),
        )
        existing_rules = existing_rules[-MAX_STYLE_RULES:]

    profile["rules"] = existing_rules
    return profile


# ---------------------------------------------------------------------------
# LLM-based extraction
# ---------------------------------------------------------------------------

def extract_and_merge_style_rules(original: str, edited: str) -> int:
    """
    Extract writing style rules by comparing original LLM text to user edits,
    then merge them into the global style profile.

    This runs in a background thread (called via run_in_executor) so it
    doesn't block the approve response.  Uses Claude Haiku for speed and
    cost (~$0.001 per call).

    Args:
        original: The original text generated by the LLM
        edited: The user's edited version of the same text

    Returns:
        Number of new rules extracted and merged (0 if none found or on error)
    """
    try:
        profile = load_style_profile()
        existing_rule_strings = [r["rule"] for r in profile.get("rules", [])]

        # Build the extraction prompt — tells the LLM to compare the two
        # versions and find deliberate style preferences.  Existing rules are
        # included so the LLM can avoid re-extracting duplicates.
        existing_rules_json = json.dumps(existing_rule_strings, indent=2)
        prompt = f"""Compare the ORIGINAL and EDITED versions of this scientific/toxicology text.
The editor made deliberate style changes. Extract specific, reusable writing
style rules that the editor is consistently applying.

Focus on these categories:
- terminology: preferred word choices and technical terms
- grammar: comma usage, voice (active/passive), tense preferences
- phrasing: preferred sentence constructions, transition patterns
- structure: paragraph organization, how information is ordered
- formatting: citation style, abbreviation conventions
- tone: formality level, hedging language, precision

EXISTING RULES (already learned — do NOT re-extract these):
{existing_rules_json}

ORIGINAL TEXT:
{original}

EDITED TEXT:
{edited}

Return ONLY a JSON array of new rules not already covered above:
[{{"rule": "description of the style preference", "category": "terminology|grammar|phrasing|structure|formatting|tone"}}]

If no new rules are evident, return an empty array: []"""

        # Use Haiku for speed and cost — style rule extraction doesn't need
        # the full reasoning power of Sonnet/Opus.
        # llm_generate_json handles endpoint creation, fence stripping,
        # and JSON parsing in one call.
        new_rules = llm_generate_json(
            "style-rule-extractor",
            prompt,
            system=(
                "You are a writing style analyst. Compare original and edited text "
                "to identify deliberate style preferences. Output ONLY valid JSON."
            ),
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
        )

        if not isinstance(new_rules, list) or len(new_rules) == 0:
            logger.info("Style extraction found no new rules")
            return 0

        # Merge extracted rules into the profile and save
        count_before = len(profile.get("rules", []))
        merge_rules(profile, new_rules)
        save_style_profile(profile)
        count_after = len(profile.get("rules", []))

        new_count = count_after - count_before
        logger.info(
            "Style learning: extracted %d rules, %d new (total: %d)",
            len(new_rules), max(new_count, 0), count_after,
        )
        return len(new_rules)

    except Exception:
        # Style learning is non-critical — log the error but don't crash
        # the approve flow
        logger.error("Style rule extraction failed:\n%s", traceback.format_exc())
        return 0
