#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - SQLite 연결과 테이블 생성 (2026-11-25 스키마 v2: 사용자별 학습, 시험, 설정 추가)
# 파일 위치: src/db.py

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "smartvoca.db"
MEMORY_DB = ":memory:"

# 학습 기록 테이블은 user_id 로 계정별로 나눈다. word 는 모든 계정이 함께 쓰는 단어장이다.
# v1 에서 바뀐 테이블(word_state, study_session, attempt)은 init_schema 가 옮겨 담는다.
SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS app_user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_setting (
        user_id INTEGER PRIMARY KEY,
        daily_target INTEGER NOT NULL DEFAULT 20,
        review_ratio INTEGER NOT NULL DEFAULT 100,
        exam_count INTEGER NOT NULL DEFAULT 10,
        exam_direction TEXT NOT NULL DEFAULT 'mix',
        exam_form TEXT NOT NULL DEFAULT 'mix'
    )
    """,
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
        user_id INTEGER NOT NULL,
        word_id INTEGER NOT NULL REFERENCES word(id) ON DELETE CASCADE,
        consecutive_correct INTEGER NOT NULL DEFAULT 0,
        first_studied_on TEXT,
        last_studied_on TEXT,
        in_review INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, word_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
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
        user_id INTEGER NOT NULL,
        word_id INTEGER NOT NULL REFERENCES word(id) ON DELETE CASCADE,
        block TEXT NOT NULL CHECK (block IN ('new', 'review')),
        selected_meaning TEXT NOT NULL,
        is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
        attempted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        question_count INTEGER NOT NULL,
        direction TEXT NOT NULL CHECK (direction IN ('en2ko', 'ko2en', 'mix')),
        form TEXT NOT NULL CHECK (form IN ('choice', 'short', 'ox', 'mix'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exam_item (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL REFERENCES exam_session(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        word_id INTEGER NOT NULL REFERENCES word(id) ON DELETE CASCADE,
        direction TEXT NOT NULL CHECK (direction IN ('en2ko', 'ko2en')),
        form TEXT NOT NULL CHECK (form IN ('choice', 'short', 'ox')),
        prompt TEXT NOT NULL,
        options_json TEXT,
        correct_answer TEXT NOT NULL,
        selected_answer TEXT,
        is_correct INTEGER CHECK (is_correct IN (0, 1)),
        answered_at TEXT
    )
    """,
]

V1_TABLES = ["word_state", "study_session", "attempt"]


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


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _needs_v2_migration(conn):
    """word_state 에 user_id 열이 없으면 v1 DB다."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'word_state'"
    ).fetchone()
    return exists is not None and "user_id" not in _columns(conn, "word_state")


def _copy_v1_rows(conn):
    """v1 기록을 v2 테이블로 옮기고 v1 테이블을 지운다. 기존 기록은 user_id 1 계정에 귀속한다."""
    conn.execute(
        "INSERT INTO study_session (id, user_id, session_date, started_at, finished_at, new_target) "
        "SELECT id, 1, session_date, started_at, finished_at, new_target FROM study_session_v1"
    )
    conn.execute(
        "INSERT INTO word_state (user_id, word_id, consecutive_correct, first_studied_on, last_studied_on, in_review) "
        "SELECT 1, word_id, consecutive_correct, first_studied_on, last_studied_on, in_review FROM word_state_v1"
    )
    conn.execute(
        "INSERT INTO attempt (id, session_id, user_id, word_id, block, selected_meaning, is_correct, attempted_at) "
        "SELECT id, session_id, 1, word_id, block, selected_meaning, is_correct, attempted_at FROM attempt_v1"
    )
    for table in ["attempt_v1", "study_session_v1", "word_state_v1"]:
        conn.execute(f"DROP TABLE {table}")


def init_schema(conn):
    """테이블이 없으면 만든다. v1 DB면 기록을 v2로 옮긴다. 이미 v2면 아무것도 하지 않는다."""
    migrating = _needs_v2_migration(conn)
    if migrating:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in V1_TABLES:
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    if migrating:
        _copy_v1_rows(conn)
    conn.commit()
    if migrating:
        conn.execute("PRAGMA foreign_keys = ON")
