"""Consistent live-SQLite backup including committed WAL pages; no raw copies."""
import argparse
from pathlib import Path
import sqlite3
from app.db import database_path


def backup_database(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    if destination.exists() or source == destination:
        raise FileExistsError("Choose a new backup filename; existing files are never overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=10)
    writer = sqlite3.connect(destination, timeout=10)
    try:
        reader.backup(writer)
        if writer.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
    finally:
        writer.close()
        reader.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    backup_database(database_path(), arguments.output)
    print(f"SQLite backup created: {arguments.output.resolve()}")
