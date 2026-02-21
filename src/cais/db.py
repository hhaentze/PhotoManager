import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


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
                size INTEGER NOT NULL
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

    def get_known_state(self) -> Dict[str, Tuple[float, int]]:
        """Returns a mapping of {path: (mtime, size)} for O(1) reconciliation."""
        cursor = self.conn.execute("""
            SELECT l.path, l.mtime, a.size 
            FROM locations l 
            JOIN assets a ON l.hash = a.hash
        """)
        return {row[0]: (row[1], row[2]) for row in cursor}

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

    def remove_paths(self, paths: List[str]) -> None:
        """Removes paths from the index and cleans up orphaned assets."""
        with self.conn:
            self.conn.executemany("DELETE FROM locations WHERE path = ?;", [(p,) for p in paths])
            self.conn.execute("""
                DELETE FROM assets WHERE hash NOT IN (SELECT hash FROM locations);
            """)

    def get_all_hashes(self) -> set[str]:
        """Returns a set of all known asset hashes for fast O(1) in-memory lookups."""
        cursor = self.conn.execute("SELECT hash FROM assets")
        return {row[0] for row in cursor}

    def get_missing_hashes(self, target_db_path: Path | str) -> Set[str]:
        """Cross-database query: Returns hashes present here, but missing in target."""
        self.conn.execute("ATTACH DATABASE ? AS target", (str(target_db_path),))
        cursor = self.conn.execute("""
            SELECT hash FROM main.assets 
            EXCEPT 
            SELECT hash FROM target.assets;
        """)
        missing = {row[0] for row in cursor}
        self.conn.execute("DETACH DATABASE target")
        return missing

    def get_duplicates(self) -> dict[str, list[str]]:
        """Returns a mapping of {hash: [path1, path2, ...]} for duplicated assets."""
        cursor = self.conn.execute("""
            SELECT hash, path FROM locations
            WHERE hash IN (
                SELECT hash FROM locations GROUP BY hash HAVING COUNT(path) > 1
            )
            ORDER BY hash;
        """)
        dupes: dict[str, list[str]] = {}
        for file_hash, path in cursor:
            dupes.setdefault(file_hash, []).append(path)
        return dupes

    def get_path_for_hash(self, file_hash: str) -> str | None:
        """Returns one valid path for a given hash to facilitate file copying."""
        cursor = self.conn.execute("SELECT path FROM locations WHERE hash = ? LIMIT 1", (file_hash,))
        row = cursor.fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()
