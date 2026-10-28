#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 학습 기록 집계 단위 테스트 (FR-04)
# 파일 위치: tests/test_report_service.py

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import report_service  # noqa: E402
import study_service  # noqa: E402
import word_service  # noqa: E402

DAY1 = "2026-10-21"


class ReportServiceTest(unittest.TestCase):
    def setUp(self):
        study_service.reset_state()
        self.conn = db.connect(db.MEMORY_DB)

    def tearDown(self):
        study_service.reset_state()
        self.conn.close()

    def test_daily_summary_counts_new_words_and_rate(self):
        # FR-04.1, FR-04.2: 날짜별 학습 단어 수와 정답률
        for english, meaning in [("apple", "사과"), ("banana", "바나나"), ("cherry", "체리"), ("grape", "포도")]:
            word_service.add_word(self.conn, english, meaning)
        active = study_service.resume_or_start_session(self.conn, DAY1)
        rng = random.Random(3)
        answered = 0
        while True:
            question = study_service.current_question(self.conn, active, rng)
            if question is None:
                break
            wrong = answered == 0
            selected = next(o for o in question["options"] if o != question["correct_meaning"]) if wrong else question["correct_meaning"]
            result = study_service.submit_answer(self.conn, question["word_id"], selected, DAY1)
            answered += 1
            if result["session_finished"]:
                break
        rows = report_service.daily_summary(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], DAY1)
        self.assertEqual(rows[0]["learned"], 4)
        self.assertEqual(rows[0]["attempts"], answered)
        self.assertEqual(rows[0]["rate"], round((answered - 1) * 100.0 / answered, 1))

    def test_mastery_summary_counts_states(self):
        # FR-04.3: 완벽 암기와 복습 대기 수
        word_service.add_word(self.conn, "apple", "사과")
        word_service.add_word(self.conn, "banana", "바나나")
        self.conn.execute("UPDATE word_state SET consecutive_correct = 3 WHERE word_id = 1")
        self.conn.execute("UPDATE word_state SET in_review = 1 WHERE word_id = 2")
        self.conn.commit()
        summary = report_service.mastery_summary(self.conn)
        self.assertEqual(summary, {"mastered": 1, "review_pending": 1})

    def test_empty_history_returns_no_rate(self):
        self.assertEqual(report_service.daily_summary(self.conn), [])


if __name__ == "__main__":
    unittest.main()
