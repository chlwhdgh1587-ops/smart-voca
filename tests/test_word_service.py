#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 단어 관리 단위 테스트 (FR-01)
# 파일 위치: tests/test_word_service.py

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import word_service  # noqa: E402


class WordServiceTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(db.MEMORY_DB)

    def tearDown(self):
        self.conn.close()

    def test_add_word_normalizes_english_and_creates_state(self):
        # FR-01.1: 영어는 소문자와 공백 제거로 정규화, 학습 상태 행도 함께 생성
        word_id = word_service.add_word(self.conn, "  Apple ", "사과")
        word = word_service.get_word(self.conn, word_id)
        state = self.conn.execute(
            "SELECT consecutive_correct, in_review FROM word_state WHERE word_id = ?", (word_id,)
        ).fetchone()
        self.assertEqual(word["english"], "apple")
        self.assertEqual(state["consecutive_correct"], 0)
        self.assertEqual(state["in_review"], 0)

    def test_duplicate_english_is_rejected_ignoring_case(self):
        # FR-01.1: 같은 영어 단어는 한 번만 등록된다
        word_service.add_word(self.conn, "apple", "사과")
        with self.assertRaises(word_service.DuplicateWordError):
            word_service.add_word(self.conn, "APPLE", "애플")

    def test_empty_meaning_is_rejected(self):
        with self.assertRaises(word_service.WordError):
            word_service.add_word(self.conn, "apple", "   ")

    def test_update_keeps_learning_state(self):
        # FR-01.2: 수정해도 학습 상태는 유지된다
        word_id = word_service.add_word(self.conn, "apple", "사과")
        self.conn.execute("UPDATE word_state SET consecutive_correct = 2 WHERE word_id = ?", (word_id,))
        self.conn.commit()
        word_service.update_word(self.conn, word_id, "apple", "사과 (과일)", "An apple a day.")
        state = self.conn.execute(
            "SELECT consecutive_correct FROM word_state WHERE word_id = ?", (word_id,)
        ).fetchone()
        self.assertEqual(word_service.get_word(self.conn, word_id)["meaning"], "사과 (과일)")
        self.assertEqual(state["consecutive_correct"], 2)

    def test_delete_removes_state_and_attempts(self):
        # FR-01.3: 삭제하면 학습 상태와 답안 기록도 함께 삭제된다
        word_id = word_service.add_word(self.conn, "apple", "사과")
        self.conn.execute(
            "INSERT INTO study_session (session_date, started_at, new_target) VALUES ('2026-10-21', 'x', 20)"
        )
        self.conn.execute(
            "INSERT INTO attempt (session_id, word_id, block, selected_meaning, is_correct, attempted_at) "
            "VALUES (1, ?, 'new', '사과', 1, '2026-10-21T10:00:00')",
            (word_id,),
        )
        self.conn.commit()
        word_service.delete_word(self.conn, word_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM word_state").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0], 0)

    def test_delete_missing_word_raises(self):
        with self.assertRaises(word_service.WordError):
            word_service.delete_word(self.conn, 999)


if __name__ == "__main__":
    unittest.main()
