#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 설정 검증과 DB v1→v2 이관 단위 테스트 (VOCA-FR-062, VOCA-NFR-002·003)
# 파일 위치: tests/test_settings_and_migration.py

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import settings_service  # noqa: E402

VALID = {
    "daily_target": "15",
    "review_ratio": "50",
    "exam_count": "10",
    "exam_direction": "ko2en",
    "exam_form": "ox",
}

# 2026-10-21 ~ 11-18에 쓰던 v1 스키마 (word_state·study_session·attempt는 user_id가 없다)
V1_SCHEMA = [
    """CREATE TABLE word (
        id INTEGER PRIMARY KEY AUTOINCREMENT, english TEXT NOT NULL UNIQUE,
        meaning TEXT NOT NULL, example TEXT, created_at TEXT NOT NULL)""",
    """CREATE TABLE word_state (
        word_id INTEGER PRIMARY KEY REFERENCES word(id) ON DELETE CASCADE,
        consecutive_correct INTEGER NOT NULL DEFAULT 0, first_studied_on TEXT,
        last_studied_on TEXT, in_review INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE study_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_date TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, new_target INTEGER NOT NULL)""",
    """CREATE TABLE attempt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES study_session(id) ON DELETE CASCADE,
        word_id INTEGER NOT NULL REFERENCES word(id) ON DELETE CASCADE,
        block TEXT NOT NULL CHECK (block IN ('new', 'review')),
        selected_meaning TEXT NOT NULL,
        is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
        attempted_at TEXT NOT NULL)""",
]


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(db.MEMORY_DB)

    def tearDown(self):
        self.conn.close()

    def test_defaults_when_nothing_saved(self):
        self.assertEqual(settings_service.get_settings(self.conn, 1), settings_service.DEFAULT_SETTINGS)

    def test_save_then_read_back(self):
        # VOCA-FR-062: 저장한 설정은 다시 읽어도 그대로 남는다
        settings_service.save_settings(self.conn, 1, VALID)
        saved = settings_service.get_settings(self.conn, 1)
        self.assertEqual(saved["daily_target"], 15)
        self.assertEqual(saved["exam_form"], "ox")
        self.assertEqual(saved["review_ratio"], 50)

    def test_invalid_values_are_rejected(self):
        bad_cases = [
            {"daily_target": "0"},
            {"daily_target": "abc"},
            {"review_ratio": "30"},
            {"exam_count": "7"},
            {"exam_direction": "essay"},
            {"exam_form": "essay"},
        ]
        for patch in bad_cases:
            values = {**VALID, **patch}
            with self.subTest(patch=patch), self.assertRaises(settings_service.SettingError):
                settings_service.validate_settings(values)


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.path = str(Path(self.temp_dir) / "v1.db")
        raw = sqlite3.connect(self.path)
        raw.execute("PRAGMA foreign_keys = ON")
        for statement in V1_SCHEMA:
            raw.execute(statement)
        raw.execute("INSERT INTO word (id, english, meaning, created_at) VALUES (1, 'apple', '사과', 'x')")
        raw.execute("INSERT INTO word (id, english, meaning, created_at) VALUES (2, 'banana', '바나나', 'x')")
        raw.execute("INSERT INTO word_state (word_id, consecutive_correct, first_studied_on, in_review) "
                    "VALUES (1, 3, '2026-10-21', 0)")
        raw.execute("INSERT INTO study_session (id, session_date, started_at, new_target) "
                    "VALUES (5, '2026-10-21', 'x', 20)")
        raw.execute("INSERT INTO attempt (session_id, word_id, block, selected_meaning, is_correct, attempted_at) "
                    "VALUES (5, 1, 'new', '사과', 1, '2026-10-21T10:00:00')")
        raw.commit()
        raw.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_v1_records_move_to_user_one_and_keep_ids(self):
        # 기존 기록은 계정 1번에 귀속되고, 세션·답안 번호와 연결이 유지된다
        conn = db.connect(self.path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM word").fetchone()[0], 2)
            state = conn.execute("SELECT user_id, word_id, consecutive_correct FROM word_state").fetchone()
            self.assertEqual((state["user_id"], state["word_id"], state["consecutive_correct"]), (1, 1, 3))
            session = conn.execute("SELECT id, user_id FROM study_session").fetchone()
            self.assertEqual((session["id"], session["user_id"]), (5, 1))
            attempt = conn.execute("SELECT session_id, user_id, is_correct FROM attempt").fetchone()
            self.assertEqual((attempt["session_id"], attempt["user_id"], attempt["is_correct"]), (5, 1, 1))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertTrue({"app_user", "exam_session", "exam_item", "user_setting"} <= tables)
            self.assertFalse({"word_state_v1", "study_session_v1", "attempt_v1"} & tables)
        finally:
            conn.close()

    def test_reopening_after_migration_changes_nothing(self):
        db.connect(self.path).close()
        conn = db.connect(self.path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
