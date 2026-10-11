"""Persistent experiment log (stdlib sqlite3). Logging never breaks a run."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "runs.db"


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL, algorithm TEXT, mixer TEXT, noise TEXT, cvar REAL,
        tickers TEXT, K INTEGER, risk_q REAL, p INTEGER, shots INTEGER,
        optimizer TEXT, source TEXT, bitstring TEXT, energy REAL,
        sharpe REAL, seconds REAL)""")
    return c


def log_run(cfg: dict, bitstring, energy, sharpe, seconds):
    try:
        c = _conn()
        c.execute(
            "INSERT INTO runs (ts, algorithm, mixer, noise, cvar, tickers, K, risk_q,"
            " p, shots, optimizer, source, bitstring, energy, sharpe, seconds)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), cfg.get("algorithm"), cfg.get("mixer", "standard"),
             cfg.get("noise", "ideal"), float(cfg.get("cvar_alpha", 1.0)),
             ",".join(cfg.get("tickers", [])), cfg.get("K"), cfg.get("risk_q"),
             cfg.get("p"), cfg.get("shots"), cfg.get("optimizer"),
             cfg.get("source", "mock"), bitstring,
             float(energy) if energy is not None else None,
             float(sharpe) if sharpe is not None else None, float(seconds or 0)))
        rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.commit()
        c.close()
        return rid
    except Exception:
        return None


def list_runs(limit=20):
    try:
        c = _conn()
        rows = c.execute(
            "SELECT id, ts, algorithm, mixer, noise, cvar, tickers, K,"
            " bitstring, energy, sharpe, seconds FROM runs"
            " ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        c.close()
        keys = ["id", "ts", "algorithm", "mixer", "noise", "cvar", "tickers",
                "K", "bitstring", "energy", "sharpe", "seconds"]
        return [dict(zip(keys, r)) for r in rows]
    except Exception:
        return []


def clear_runs():
    try:
        c = _conn()
        c.execute("DELETE FROM runs")
        c.commit()
        c.close()
        return True
    except Exception:
        return False
