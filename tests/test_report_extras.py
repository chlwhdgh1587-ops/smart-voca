#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 진도, 시험 추이, 자주 틀린 단어 집계 단위 테스트 (VOCA-FR-031~034)
# 파일 위치: tests/test_report_extras.py

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import exam_service  # noqa: E402
import report_service  # noqa: E402
import study_service  # noqa: E402
import word_service  # noqa: E402

USER = 1
DAY1 = "2026-10-21"
WORDS = [("apple", "사과"), ("banana", "바나나"), ("cherry", "체리"), ("grape", "포도"), ("lemon", "레몬")]


class ReportExtrasTest(unittest.TestCase):
    def setUp(self):
        study_service.reset_state()
        self.conn = db.connect(db.MEMORY_DB)
        for english, meaning in WORDS:
            word_service.add_word(self.conn, english, meaning)

    def tearDown(self):
        study_service.reset_state()
        self.conn.close()

    def test_weak_words_count_study_and_exam_wrong_answers(self):
        # VOCA-FR-033: 암기와 시험에서 틀린 횟수를 합쳐 많이 틀린 순서로 보여 준다
        active = study_service.resume_or_start_session(self.conn, USER, DAY1)
        question = study_service.current_question(self.conn, active, random.Random(1))
        wrong = next(option for option in question["options"] if option != question["correct_meaning"])
        study_service.submit_answer(self.conn, USER, question["word_id"], wrong, DAY1)
        weak = report_service.weak_words(self.conn, USER)
        self.assertEqual(weak[0]["english"], question["english"])
        self.assertEqual(weak[0]["wrong"], 1)

    def test_progress_counts_mastered_words_and_day(self):
        # VOCA-FR-031: 현재 일차와 암기한 단어 수 / 전체
        progress = report_service.progress_summary(self.conn, USER, DAY1)
        self.assertEqual(progress["day_number"], 1)
        self.assertEqual(progress["total"], len(WORDS))
        self.assertEqual(progress["mastered"], 0)

    def test_exam_trend_lists_finished_exams_by_date(self):
        # VOCA-FR-032: 끝난 시험만 회차와 날짜별 정답률에 들어간다
        exam_id = exam_service.create_exam(self.conn, USER, 2, "en2ko", "short", DAY1, random.Random(2))
        self.assertEqual(report_service.exam_trend(self.conn, USER)["sessions"], [])
        for _ in range(2):
            item = exam_service.current_item(self.conn, exam_id)
            exam_service.answer_item(self.conn, USER, exam_id, item["id"], item["correct_answer"], DAY1)
        trend = report_service.exam_trend(self.conn, USER)
        self.assertEqual(len(trend["sessions"]), 1)
        self.assertEqual(trend["sessions"][0]["rate"], 100.0)
        self.assertEqual(trend["daily"][0]["date"], DAY1)


if __name__ == "__main__":
    unittest.main()
