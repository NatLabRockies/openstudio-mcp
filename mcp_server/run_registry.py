from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  name TEXT,
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  started_at REAL,
  ended_at REAL,
  pid INTEGER,
  run_dir TEXT NOT NULL,
  osw_path TEXT NOT NULL,
  epw_path TEXT,
  exit_code INTEGER,
  error TEXT
);
'''

def _db_path(run_root: Path) -> Path:
    return run_root / "run_registry.sqlite3"

def init_db(run_root: Path) -> None:
    db = _db_path(run_root)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

def insert_run(run_root: Path, row: Dict[str, Any]) -> None:
    init_db(run_root)
    conn = sqlite3.connect(_db_path(run_root))
    try:
        cols = ",".join(row.keys())
        qs = ",".join(["?"] * len(row))
        conn.execute(f"INSERT INTO runs ({cols}) VALUES ({qs})", list(row.values()))
        conn.commit()
    finally:
        conn.close()

def update_run(run_root: Path, run_id: str, **fields: Any) -> None:
    if not fields:
        return
    init_db(run_root)
    conn = sqlite3.connect(_db_path(run_root))
    try:
        sets = ",".join([f"{k}=?" for k in fields.keys()])
        vals = list(fields.values()) + [run_id]
        conn.execute(f"UPDATE runs SET {sets} WHERE run_id=?", vals)
        conn.commit()
    finally:
        conn.close()

def get_run(run_root: Path, run_id: str) -> Optional[Dict[str, Any]]:
    init_db(run_root)
    conn = sqlite3.connect(_db_path(run_root))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()
