#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - SQLite 연결과 테이블 생성
# 파일 위치: src/db.py

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "smartvoca.db"
MEMORY_DB = ":memory:"

# 데이터 설계서 2절의 테이블 정의
SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS word (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        english TEXT NOT NULL UNIQUE,
        meaning TEXT NOT NULL,
        example TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS word_state (
        word_id INTEGER PRIMARY KEY REFERENCES word(id) ON DELETE CASCADE,
        consecutive_correct INTEGER NOT NULL DEFAULT 0,
        first_studied_on TEXT,
        last_studied_on TEXT,
        in_review INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_date TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        new_target INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attempt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES study_session(id) ON DELETE CASCADE,
        word_id INTEGER NOT NULL REFERENCES word(id) ON DELETE CASCADE,
        block TEXT NOT NULL CHECK (block IN ('new', 'review')),
        selected_meaning TEXT NOT NULL,
        is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
        attempted_at TEXT NOT NULL
    )
    """,
]


def connect(db_path=None):
    """SQLite 연결을 열고 외래키 설정과 테이블 생성을 보장한다."""
    path_text = str(db_path) if db_path else str(DEFAULT_DB_PATH)
    if path_text != MEMORY_DB:
        Path(path_text).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path_text)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn):
    """테이블이 없으면 만든다. 이미 있으면 아무것도 하지 않는다."""
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()
