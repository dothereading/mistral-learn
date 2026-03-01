"""Spaced repetition scheduler using FSRS algorithm."""

import sqlite3
from datetime import datetime, timezone
from fsrs import Scheduler, Card, Rating

scheduler = Scheduler()

RATING_MAP = {
    1: Rating.Again,
    2: Rating.Hard,
    3: Rating.Good,
    4: Rating.Easy,
}


def get_due_reviews(conn: sqlite3.Connection, limit: int = 10,
                    item_type: str | None = None) -> list[dict]:
    """Return review items that are due now (or new items with no due_date)."""
    now = datetime.now(timezone.utc).isoformat()

    query = """
        SELECT * FROM review_items
        WHERE (due_date IS NULL OR due_date <= ?)
    """
    params: list = [now]

    if item_type:
        query += " AND item_type = ?"
        params.append(item_type)

    query += " ORDER BY due_date ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def log_review(conn: sqlite3.Connection, item_id: int, rating: int) -> dict:
    """Log a review and update scheduling via FSRS. Returns the updated item."""
    if rating not in RATING_MAP:
        raise ValueError(f"Rating must be 1-4, got {rating}")

    row = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError(f"No review item with id {item_id}")

    # Build an FSRS Card from stored fields
    card = Card()

    # Only restore state if the card has been reviewed before;
    # a fresh Card() is what FSRS expects for first-time reviews.
    if row["last_reviewed"]:
        card.stability = row["stability"] or 0.0
        card.difficulty = row["difficulty"] or 0.0
        card.due = datetime.fromisoformat(row["due_date"]) if row["due_date"] else card.due
        card.last_review = datetime.fromisoformat(row["last_reviewed"])
        card.step = row["review_count"] or 0

    # Schedule the next review
    card, review_log = scheduler.review_card(card, RATING_MAP[rating])

    # Map FSRS state back to our state string
    state_map = {0: "new", 1: "learning", 2: "review", 3: "relearning"}
    new_state = state_map.get(card.state.value, "review")

    # Track lapses ourselves: increment when rating is Again (forgot)
    current_lapses = row["lapses"] or 0
    if rating == 1:
        current_lapses += 1

    conn.execute("""
        UPDATE review_items SET
            stability = ?,
            difficulty = ?,
            due_date = ?,
            last_reviewed = ?,
            review_count = ?,
            lapses = ?,
            state = ?,
            updated_at = datetime('now')
        WHERE id = ?
    """, (
        card.stability,
        card.difficulty,
        card.due.isoformat(),
        card.last_review.isoformat(),
        card.step,
        current_lapses,
        new_state,
        item_id,
    ))
    conn.commit()

    updated = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    return dict(updated)


def add_review_item(conn: sqlite3.Connection, item_type: str, language: str,
                    word: str | None = None, translation: str | None = None,
                    pattern_name: str | None = None,
                    pattern_description: str | None = None,
                    context: str | None = None,
                    category: str | None = None) -> dict:
    """Add a new vocab or grammar item to the SRS deck. Returns the created item."""
    if item_type == "vocab" and not word:
        raise ValueError("Vocab items require a 'word'")
    if item_type == "grammar" and not pattern_name:
        raise ValueError("Grammar items require a 'pattern_name'")

    # Check for duplicates
    if item_type == "vocab":
        existing = conn.execute(
            "SELECT id FROM review_items WHERE item_type = 'vocab' AND word = ? AND language = ?",
            (word, language)
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT id FROM review_items WHERE item_type = 'grammar' AND pattern_name = ? AND language = ?",
            (pattern_name, language)
        ).fetchone()

    if existing:
        return dict(conn.execute("SELECT * FROM review_items WHERE id = ?",
                                 (existing["id"],)).fetchone())

    cursor = conn.execute("""
        INSERT INTO review_items
            (item_type, word, translation, pattern_name, pattern_description,
             context, category, language)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (item_type, word, translation, pattern_name, pattern_description,
          context, category, language))
    conn.commit()

    created = conn.execute("SELECT * FROM review_items WHERE id = ?",
                           (cursor.lastrowid,)).fetchone()
    return dict(created)
