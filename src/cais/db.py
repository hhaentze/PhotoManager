import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class DataPoint:
    hash: str
    phash: Optional[str]
    size: int
    mtime: str


@dataclass
class DuplicateGroup:
    original: Optional[str]
    duplicates: list[str]
    match_type: str  # "hash" or "phash"


class IndexDB:
    def __init__(self, db_path: Path | str, db_name: Optional[str] = None):
        self.db_path = Path(db_path)
        file_exists = self.db_path.exists()

        if db_name is not None:
            # Creation mode
            if file_exists:
                raise FileExistsError(f"Database already exists at {self.db_path}")
            self.conn = sqlite3.connect(self.db_path, isolation_level=None)
            self._init_schema()
            self.set_metadata("name", db_name)

        else:
            # Load mode
            if not file_exists:
                raise FileNotFoundError("Database name not specified")
            self.conn = sqlite3.connect(self.db_path, isolation_level=None)

    def _init_schema(self) -> None:
        """Creates the schema if it doesn't exist."""
        self.conn.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS assets (
                hash TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                phash TEXT
            );
            CREATE TABLE IF NOT EXISTS locations (
                path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                mtime REAL NOT NULL,
                FOREIGN KEY (hash) REFERENCES assets(hash)
            );
            CREATE INDEX IF NOT EXISTS idx_locations_hash ON locations(hash);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
        """)

    def set_metadata(self, key: str, value: str) -> None:
        """Stores arbitrary key-value pairs (like the db name)."""
        self.conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))

    def get_metadata(self, key: str) -> str | None:
        """Retrieves metadata by key."""
        cursor = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_known_state(self) -> Dict[str, DataPoint]:
        """Returns a mapping of {path: (mtime, size, phash)} for O(1) reconciliation."""
        cursor = self.conn.execute("""
            SELECT l.path, a.hash, a.phash, a.size, l.mtime
            FROM locations l 
            JOIN assets a ON l.hash = a.hash
        """)
        return {row[0]: DataPoint(row[1], row[2], row[3], row[4]) for row in cursor}

    def get_status_stats(self) -> dict:
        """Returns aggregated database statistics."""
        cursor = self.conn.execute("""
            SELECT 
                (SELECT COUNT(*) FROM locations),
                (SELECT COUNT(*) FROM assets),
                (SELECT SUM(size) FROM assets)
        """)
        loc_count, asset_count, total_size = cursor.fetchone()
        return {
            "name": self.get_metadata("name") or "Unnamed",
            "locations": loc_count or 0,
            "assets": asset_count or 0,
            "size": total_size or 0,
        }

    def upsert_files(self, file_data: List[Tuple[str, str, int, float]]) -> None:
        """Batch inserts or updates files. Expected tuple: (path, hash, size, mtime)"""
        with self.conn:  # Context manager handles the transaction chunk
            self.conn.executemany(
                """
                INSERT INTO assets (hash, size) VALUES (?, ?)
                ON CONFLICT(hash) DO NOTHING;
            """,
                [(row[1], row[2]) for row in file_data],
            )

            self.conn.executemany(
                """
                INSERT INTO locations (path, hash, mtime) VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET hash=excluded.hash, mtime=excluded.mtime;
            """,
                [(row[0], row[1], row[3]) for row in file_data],
            )

    def update_phashes(self, phash_data: List[Tuple[str, str]]) -> None:
        """Batch updates perceptual hashes for existing assets. Expected tuple: (hash, phash)"""
        with self.conn:
            self.conn.executemany(
                """
                UPDATE assets SET phash = ? WHERE hash = ?;
                """,
                [(row[1], row[0]) for row in phash_data],
            )

    def remove_paths(self, paths: List[str]) -> None:
        """Removes paths from the index and cleans up orphaned assets."""
        with self.conn:
            self.conn.executemany("DELETE FROM locations WHERE path = ?;", [(p,) for p in paths])
            self.conn.execute("""
                DELETE FROM assets WHERE hash NOT IN (SELECT hash FROM locations);
            """)

    def get_all_duplicates(self) -> dict[str, DuplicateGroup]:
        """Return {hash_or_phash: DuplicateGroup} for exact + perceptual duplicates."""

        duplicates: dict[str, DuplicateGroup] = {}

        # --- Exact duplicates (same hash, multiple paths) ---
        cursor = self.conn.execute("""
            SELECT l.hash, l.path
            FROM locations l
            WHERE l.hash IN (
                SELECT hash
                FROM locations
                GROUP BY hash
                HAVING COUNT(*) > 1
            )
            ORDER BY l.hash;
        """)

        exact_map: dict[str, list[str]] = defaultdict(list)
        for h, path in cursor:
            exact_map[h].append(path)

        for h, paths in exact_map.items():
            duplicates[h] = DuplicateGroup(
                original=None,
                duplicates=paths,
                match_type="hash",
            )

        # --- Perceptual duplicates (same phash, different hashes) ---
        cursor = self.conn.execute("""
            SELECT a.phash, l.path
            FROM assets a
            JOIN locations l ON l.hash = a.hash
            WHERE a.phash IS NOT NULL
            AND a.phash IN (
                SELECT phash
                FROM assets
                WHERE phash IS NOT NULL
                GROUP BY phash
                HAVING COUNT(DISTINCT hash) > 1
            )
            ORDER BY a.phash;
        """)

        phash_map: dict[str, list[str]] = defaultdict(list)
        for ph, path in cursor:
            phash_map[ph].append(path)

        for ph, paths in phash_map.items():
            duplicates[ph] = DuplicateGroup(
                original=None,
                duplicates=paths,
                match_type="phash",
            )

        return duplicates

    def close(self) -> None:
        self.conn.close()
