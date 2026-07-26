import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


@dataclass
class DataPoint:
    hash: Optional[str]  # None until the file has been hashed
    phash: Optional[str]
    size: int
    mtime: float


@dataclass
class DuplicateGroup:
    original: Optional[str]
    duplicates: list[Tuple[str, str]]  # path & match_type[hash/phash]


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
                hash TEXT NOT NULL PRIMARY KEY,
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

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Run a block as one atomic transaction.

        The connection is opened in autocommit mode (isolation_level=None), so
        ``with self.conn`` does not actually roll back on error; this makes batch
        writes atomic instead of leaving partial state behind.
        """
        self.conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

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

    def upsert_files(self, file_data: List[Tuple[str, Optional[str], int, float]]) -> None:
        """Batch inserts or updates files. Expected tuple: (path, hash, size, mtime)"""
        with self._transaction():
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

    def update_phashes(self, phash_data: List[Tuple[Optional[str], str]]) -> None:
        """Batch updates perceptual hashes for existing assets. Expected tuple: (hash, phash)"""
        with self._transaction():
            self.conn.executemany(
                """
                UPDATE assets SET phash = ? WHERE hash = ?;
                """,
                [(row[1], row[0]) for row in phash_data],
            )

    def remove_paths(self, paths: List[str]) -> None:
        """Removes paths from the index and cleans up orphaned assets."""
        with self._transaction():
            self.conn.executemany("DELETE FROM locations WHERE path = ?;", [(p,) for p in paths])
            self.conn.execute("""
                DELETE FROM assets WHERE hash NOT IN (SELECT hash FROM locations);
            """)

    def get_all_duplicates(self) -> dict[str, DuplicateGroup]:
        """Return {hash_or_phash: DuplicateGroup} for exact + perceptual duplicates."""

        query = """
            WITH GroupedPaths AS (
                SELECT 
                    l.path,
                    COALESCE(a.phash, l.hash) AS group_id,
                    COUNT(l.path) OVER (PARTITION BY COALESCE(a.phash, l.hash)) AS group_size,
                    COUNT(l.path) OVER (PARTITION BY l.hash) AS hash_size
                FROM locations l
                JOIN assets a ON l.hash = a.hash
            )
            SELECT 
                group_id, 
                path, 
                CASE 
                    WHEN hash_size > 1 THEN 'hash'
                    ELSE 'phash'
                END AS match_type
            FROM GroupedPaths
            WHERE group_size > 1
            ORDER BY group_id, match_type;
        """

        cursor = self.conn.execute(query)
        grouped_data: dict[str, list[Tuple[str, str]]] = defaultdict(list)

        for group_id, path, match_type in cursor:
            grouped_data[group_id].append((path, match_type))

        # Convert the defaultdict to the final dict of DuplicateGroup dataclasses
        duplicates: dict[str, DuplicateGroup] = {
            group_id: DuplicateGroup(original=None, duplicates=paths) for group_id, paths in grouped_data.items()
        }

        return duplicates

    def close(self) -> None:
        self.conn.close()
