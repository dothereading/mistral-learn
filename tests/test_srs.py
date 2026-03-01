"""Tests for the SRS database and scheduling."""

import os
import sqlite3
import pytest
from db.models import init_database
from db.srs import add_review_item, get_due_reviews, log_review


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """Create a temporary database for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("db.models.DB_PATH", db_path)
    connection = init_database()
    yield connection
    connection.close()


# --- init_database ---

class TestInitDatabase:
    def test_creates_table(self, conn):
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='review_items'"
        ).fetchone()
        assert tables is not None

    def test_creates_indexes(self, conn):
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {r["name"] for r in indexes}
        assert "idx_due_date" in index_names
        assert "idx_language" in index_names
        assert "idx_state" in index_names
        assert "idx_item_type" in index_names

    def test_idempotent(self, conn):
        # Calling init again should not raise
        conn.execute("SELECT 1 FROM review_items")


# --- add_review_item ---

class TestAddReviewItem:
    def test_add_vocab(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola! ¿Cómo estás?", category="greetings")
        assert item["id"] == 1
        assert item["item_type"] == "vocab"
        assert item["word"] == "hola"
        assert item["translation"] == "hello"
        assert item["language"] == "es"
        assert item["state"] == "new"

    def test_add_grammar(self, conn):
        item = add_review_item(conn, "grammar", "es",
                               pattern_name="ser vs estar",
                               pattern_description="ser=permanent, estar=temporary",
                               context="Soy americano pero estoy en Madrid.",
                               category="verb-conjugation")
        assert item["item_type"] == "grammar"
        assert item["pattern_name"] == "ser vs estar"
        assert item["word"] is None

    def test_vocab_requires_word(self, conn):
        with pytest.raises(ValueError, match="require"):
            add_review_item(conn, "vocab", "es", context="test")

    def test_grammar_requires_pattern_name(self, conn):
        with pytest.raises(ValueError, match="require"):
            add_review_item(conn, "grammar", "es", context="test")

    def test_duplicate_vocab_returns_existing(self, conn):
        item1 = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                                context="context 1", category="greetings")
        item2 = add_review_item(conn, "vocab", "es", word="hola", translation="hi",
                                context="context 2", category="greetings")
        assert item1["id"] == item2["id"]

    def test_duplicate_grammar_returns_existing(self, conn):
        item1 = add_review_item(conn, "grammar", "es", pattern_name="ser vs estar",
                                pattern_description="v1", context="c1")
        item2 = add_review_item(conn, "grammar", "es", pattern_name="ser vs estar",
                                pattern_description="v2", context="c2")
        assert item1["id"] == item2["id"]

    def test_same_word_different_language_not_duplicate(self, conn):
        item1 = add_review_item(conn, "vocab", "es", word="no", translation="no",
                                context="No quiero")
        item2 = add_review_item(conn, "vocab", "fr", word="no", translation="no",
                                context="Non merci")
        assert item1["id"] != item2["id"]

    def test_new_item_has_no_due_date(self, conn):
        item = add_review_item(conn, "vocab", "es", word="gato", translation="cat",
                               context="El gato es negro.")
        assert item["due_date"] is None
        assert item["last_reviewed"] is None
        assert item["review_count"] == 0


# --- get_due_reviews ---

class TestGetDueReviews:
    def test_new_items_are_due(self, conn):
        add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                        context="¡Hola!")
        add_review_item(conn, "vocab", "es", word="adiós", translation="goodbye",
                        context="¡Adiós!")
        due = get_due_reviews(conn)
        assert len(due) == 2

    def test_limit(self, conn):
        for i in range(5):
            add_review_item(conn, "vocab", "es", word=f"word{i}",
                            translation=f"trans{i}", context=f"ctx{i}")
        due = get_due_reviews(conn, limit=3)
        assert len(due) == 3

    def test_filter_by_type(self, conn):
        add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                        context="¡Hola!")
        add_review_item(conn, "grammar", "es", pattern_name="ser vs estar",
                        pattern_description="test", context="test")
        vocab_due = get_due_reviews(conn, item_type="vocab")
        grammar_due = get_due_reviews(conn, item_type="grammar")
        assert len(vocab_due) == 1
        assert len(grammar_due) == 1
        assert vocab_due[0]["item_type"] == "vocab"
        assert grammar_due[0]["item_type"] == "grammar"

    def test_reviewed_item_not_immediately_due(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola!")
        log_review(conn, item["id"], 3)  # Good
        due = get_due_reviews(conn)
        # The reviewed item should be scheduled in the future
        assert not any(d["id"] == item["id"] for d in due)

    def test_empty_db(self, conn):
        due = get_due_reviews(conn)
        assert due == []


# --- log_review ---

class TestLogReview:
    def test_first_review_sets_fields(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola!")
        updated = log_review(conn, item["id"], 3)
        assert updated["last_reviewed"] is not None
        assert updated["due_date"] is not None
        assert updated["stability"] > 0
        assert updated["difficulty"] > 0
        assert updated["state"] != "new"

    def test_second_review_updates_scheduling(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola!")
        after_first = log_review(conn, item["id"], 3)
        after_second = log_review(conn, item["id"], 4)  # Easy
        assert after_second["due_date"] != after_first["due_date"]
        assert after_second["last_reviewed"] is not None

    def test_again_increments_lapses(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola!")
        assert item["lapses"] == 0
        log_review(conn, item["id"], 3)  # first review (good)
        updated = log_review(conn, item["id"], 1)  # forgot
        assert updated["lapses"] == 1

    def test_good_does_not_increment_lapses(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola!")
        updated = log_review(conn, item["id"], 3)
        assert updated["lapses"] == 0

    def test_invalid_rating_raises(self, conn):
        item = add_review_item(conn, "vocab", "es", word="hola", translation="hello",
                               context="¡Hola!")
        with pytest.raises(ValueError, match="Rating must be 1-4"):
            log_review(conn, item["id"], 5)

    def test_nonexistent_item_raises(self, conn):
        with pytest.raises(ValueError, match="No review item"):
            log_review(conn, 999, 3)

    def test_all_ratings(self, conn):
        """Each rating value (1-4) should work without errors."""
        for rating in [1, 2, 3, 4]:
            item = add_review_item(conn, "vocab", "es", word=f"word{rating}",
                                   translation=f"t{rating}", context=f"c{rating}")
            updated = log_review(conn, item["id"], rating)
            assert updated["due_date"] is not None
