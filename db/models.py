import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "langtutor.db")


def init_database() -> sqlite3.Connection:
    """Initialize the SQLite database and return a connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL DEFAULT 'vocab',

            -- For vocab items
            word TEXT,
            translation TEXT,

            -- For grammar items
            pattern_name TEXT,
            pattern_description TEXT,

            -- Shared fields
            context TEXT,
            category TEXT,
            language TEXT NOT NULL,

            -- FSRS fields
            stability REAL DEFAULT 0.0,
            difficulty REAL DEFAULT 0.0,
            due_date TEXT,
            last_reviewed TEXT,
            review_count INTEGER DEFAULT 0,
            lapses INTEGER DEFAULT 0,
            state TEXT DEFAULT 'new',

            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_due_date ON review_items(due_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_language ON review_items(language)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_state ON review_items(state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_type ON review_items(item_type)")
    conn.commit()
    return conn
