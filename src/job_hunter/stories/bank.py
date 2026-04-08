from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from job_hunter.database import StoryBankDB

logger = logging.getLogger(__name__)


async def extract_stories_from_evaluation(evaluation: dict, job_url: str) -> list[dict]:
    """Extract STAR+R stories from block_f of an evaluation.

    Args:
        evaluation: Full evaluation dict (as stored in job.evaluation).
        job_url: Source job URL to tag each story with.

    Returns:
        List of story dicts ready for the story bank.
    """
    blocks = evaluation.get("blocks", {})
    interview_prep = blocks.get("interview_prep", {})
    raw_stories = interview_prep.get("stories", [])

    if not raw_stories:
        logger.info(f"No stories found in evaluation for {job_url}")
        return []

    stories: list[dict] = []
    for raw in raw_stories:
        story = {
            "id": str(uuid.uuid4()),
            "title": raw.get("title", "Untitled"),
            "theme": raw.get("requirement", "general"),
            "situation": raw.get("situation", ""),
            "task": raw.get("task", ""),
            "action": raw.get("action", ""),
            "result": raw.get("result", ""),
            "reflection": raw.get("reflection", ""),
            "tags": _extract_tags(raw),
            "best_for": _extract_best_for(raw),
            "source_job_url": job_url,
            "created_at": datetime.now().isoformat(),
        }
        stories.append(story)

    logger.info(f"Extracted {len(stories)} stories from evaluation for {job_url}")
    return stories


def _extract_tags(raw_story: dict) -> list[str]:
    """Derive tags from story content."""
    tags: list[str] = []
    # Use requirement as a tag source
    requirement = raw_story.get("requirement", "")
    if requirement:
        tags.append(requirement.lower().strip())
    # Use title keywords
    title = raw_story.get("title", "")
    for word in title.lower().split():
        cleaned = word.strip(":-.,")
        if len(cleaned) > 3 and cleaned not in tags:
            tags.append(cleaned)
    return tags[:10]  # cap at 10 tags


def _extract_best_for(raw_story: dict) -> list[str]:
    """Derive best_for list from requirement and reflection."""
    best_for: list[str] = []
    requirement = raw_story.get("requirement", "")
    if requirement:
        best_for.append(requirement)
    reflection = raw_story.get("reflection", "")
    if reflection and len(reflection) > 20:
        # First sentence of reflection often indicates applicability
        first_sentence = reflection.split(".")[0].strip()
        if first_sentence and first_sentence not in best_for:
            best_for.append(first_sentence)
    return best_for


def add_stories_to_bank(db_path: Path | str, stories: list[dict]) -> int:
    """Add stories to the story bank, deduplicating by title + situation.

    Args:
        db_path: Path to the SQLite database.
        stories: List of story dicts to add.

    Returns:
        Count of new stories actually added.
    """
    sdb = StoryBankDB(db_path)
    added = 0
    try:
        for story in stories:
            title = story.get("title", "")
            situation = story.get("situation", "")
            if sdb.story_exists(title, situation):
                logger.debug(f"Skipping duplicate story: {title}")
                continue

            # Prepare the story for DB insertion (serialize lists to JSON)
            db_story = {
                "title": title,
                "theme": story.get("theme", ""),
                "situation": situation,
                "task": story.get("task", ""),
                "action": story.get("action", ""),
                "result": story.get("result", ""),
                "reflection": story.get("reflection", ""),
                "tags": json.dumps(story.get("tags", [])),
                "best_for": json.dumps(story.get("best_for", [])),
                "source_job_url": story.get("source_job_url", ""),
                "created_at": story.get("created_at", datetime.now().isoformat()),
            }
            sdb.add_story(db_story)
            added += 1
            logger.debug(f"Added story: {title}")
    finally:
        sdb.close()

    logger.info(f"Added {added} new stories to bank (skipped {len(stories) - added})")
    return added


def list_stories(db_path: Path | str) -> list[dict]:
    """Return all stories grouped by theme.

    Returns:
        List of dicts: [{theme: str, stories: [story, ...]}, ...]
    """
    sdb = StoryBankDB(db_path)
    try:
        all_stories = sdb.get_stories()
    finally:
        sdb.close()

    # Deserialize JSON fields
    for story in all_stories:
        story["tags"] = _parse_json_field(story.get("tags", "[]"))
        story["best_for"] = _parse_json_field(story.get("best_for", "[]"))

    # Group by theme
    grouped: dict[str, list[dict]] = defaultdict(list)
    for story in all_stories:
        theme = story.get("theme", "general") or "general"
        grouped[theme].append(story)

    return [{"theme": theme, "stories": stories} for theme, stories in sorted(grouped.items())]


def search_stories(db_path: Path | str, query: str) -> list[dict]:
    """Fuzzy search stories by title, theme, tags, and best_for.

    Args:
        db_path: Path to the SQLite database.
        query: Search query string.

    Returns:
        List of matching story dicts.
    """
    sdb = StoryBankDB(db_path)
    try:
        results = sdb.search_stories(query)
    finally:
        sdb.close()

    for story in results:
        story["tags"] = _parse_json_field(story.get("tags", "[]"))
        story["best_for"] = _parse_json_field(story.get("best_for", "[]"))

    return results


async def deduplicate_story(existing_stories: list[dict], new_story: dict, llm) -> bool:
    """Use LLM to check if new_story is semantically similar to any existing story.

    Args:
        existing_stories: List of existing story dicts from the bank.
        new_story: The candidate story to check.
        llm: An LLMProvider instance.

    Returns:
        True if the new story is a semantic duplicate of an existing one.
    """
    if not existing_stories:
        return False

    # Build a compact summary of existing stories for comparison
    existing_summaries = []
    for i, s in enumerate(existing_stories[:20]):  # cap to avoid token overflow
        existing_summaries.append(
            f"{i + 1}. Title: {s.get('title', 'Untitled')}\n"
            f"   Situation: {s.get('situation', 'N/A')}\n"
            f"   Result: {s.get('result', 'N/A')}"
        )

    existing_text = "\n".join(existing_summaries)

    prompt = f"""You are a deduplication engine. Determine if the NEW story below
is semantically similar to any EXISTING story. Two stories are duplicates if they
describe the same event, project, or accomplishment — even if worded differently.

## Existing Stories
{existing_text}

## New Story
Title: {new_story.get("title", "Untitled")}
Situation: {new_story.get("situation", "N/A")}
Task: {new_story.get("task", "N/A")}
Action: {new_story.get("action", "N/A")}
Result: {new_story.get("result", "N/A")}

Return JSON only:
{{"is_duplicate": true/false, "reason": "<brief explanation>", "similar_to": <index or null>}}"""

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=256)
        result = json.loads(response)
        is_dup = result.get("is_duplicate", False)
        if is_dup:
            logger.info(
                f"LLM dedup: '{new_story.get('title')}' is duplicate — "
                f"{result.get('reason', 'no reason given')}"
            )
        return is_dup
    except Exception as e:
        logger.warning(f"LLM deduplication failed: {e}; treating as non-duplicate")
        return False


def _parse_json_field(value: str | list) -> list:
    """Safely parse a JSON string field, returning a list."""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else [parsed]
    except (json.JSONDecodeError, TypeError):
        return [value] if value else []
