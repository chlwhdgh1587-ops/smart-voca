#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 일차, 자주 틀린 단어, 복습 비율, 카드 목록 단위 테스트 (VOCA-FR-011~013, VOCA-FR-061)
# 파일 위치: tests/test_study_extras.py

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import settings_service  # noqa: E402
import study_service  # noqa: E402
import word_service  # noqa: E402

USER = 1
DAY1 = "2026-10-21"
DAY2 = "2026-10-22"
WORDS = [
    ("apple", "사과"),
    ("banana", "바나나"),
    ("cherry", "체리"),
    ("grape", "포도"),
    ("lemon", "레몬"),
    ("melon", "멜론"),
    ("kiwi", "키위"),
    ("plum", "자두"),
]


def answer_all_correct(conn, active, today, rng):
    """현재 세션의 문제를 모두 맞힌다."""
    while True:
        question = study_service.current_question(conn, active, rng)
        if question is None:
            return
        result = study_service.submit_answer(conn, USER, question["word_id"], question["correct_meaning"], today)
        if result["session_finished"]:
            return


class StudyExtrasTest(unittest.TestCase):
    def setUp(self):
        study_service.reset_state()
        self.conn = db.connect(db.MEMORY_DB)
        for english, meaning in WORDS:
            word_service.add_word(self.conn, english, meaning)
        self.rng = random.Random(3)

    def tearDown(self):
        study_service.reset_state()
        self.conn.close()

    def test_day_number_counts_study_dates(self):
        # FR-011: 신규 학습을 한 날짜를 1일차부터 센다. 오늘 시작 전이면 오늘이 다음 일차
        self.assertEqual(study_service.current_day_number(self.conn, USER, DAY1), 1)
        active = study_service.resume_or_start_session(self.conn, USER, DAY1)
        answer_all_correct(self.conn, active, DAY1, self.rng)
        self.assertEqual(study_service.current_day_number(self.conn, USER, DAY1), 1)
        self.assertEqual(study_service.current_day_number(self.conn, USER, DAY2), 2)

    def test_weak_words_are_found_after_two_wrong_answers(self):
        # FR-013: 두 번 이상 틀린 단어는 자주 틀린 단어로 잡힌다
        active = study_service.resume_or_start_session(self.conn, USER, DAY1)
        target_id = None
        wrong_count = 0
        while True:
            question = study_service.current_question(self.conn, active, self.rng)
            if question is None:
                break
            if target_id is None:
                target_id = question["word_id"]
            if question["word_id"] == target_id and wrong_count < 2:
                wrong_count += 1
                selected = next(option for option in question["options"] if option != question["correct_meaning"])
            else:
                selected = question["correct_meaning"]
            result = study_service.submit_answer(self.conn, USER, question["word_id"], selected, DAY1)
            if result["session_finished"]:
                break
        self.assertIn(target_id, study_service._weak_word_ids(self.conn, USER, DAY2))

    def test_review_ratio_caps_review_block(self):
        # VOCA-FR-061: 복습 비율 50%면 복습 대상의 절반만 낸다
        settings_service.save_settings(
            self.conn, USER,
            {"daily_target": 20, "review_ratio": 50, "exam_count": 10, "exam_direction": "mix", "exam_form": "mix"},
        )
        active = study_service.resume_or_start_session(self.conn, USER, DAY1)
        answer_all_correct(self.conn, active, DAY1, self.rng)
        active = study_service.resume_or_start_session(self.conn, USER, DAY2)
        self.assertEqual(active.blocks[0].name, study_service.BLOCK_REVIEW)
        self.assertEqual(active.blocks[0].total, 4)

    def test_daily_target_comes_from_settings(self):
        # VOCA-FR-011·061: 하루 학습량 설정이 신규 블록 크기를 정한다
        settings_service.save_settings(
            self.conn, USER,
            {"daily_target": 5, "review_ratio": 100, "exam_count": 10, "exam_direction": "mix", "exam_form": "mix"},
        )
        active = study_service.resume_or_start_session(self.conn, USER, DAY1)
        new_block = next(block for block in active.blocks if block.name == study_service.BLOCK_NEW)
        self.assertEqual(new_block.total, 5)

    def test_cards_list_starts_with_studied_words_and_writes_nothing(self):
        # VOCA-FR-012: 카드는 읽기 전용이다. 오늘 먼저 공부한 단어가 맨 앞에 온다
        active = study_service.resume_or_start_session(self.conn, USER, DAY1)
        question = study_service.current_question(self.conn, active, self.rng)
        study_service.submit_answer(self.conn, USER, question["word_id"], question["correct_meaning"], DAY1)
        attempts_before = self.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0]
        words = study_service.todays_new_words(self.conn, USER, DAY1)
        self.assertEqual(words[0]["english"], question["english"])
        self.assertEqual(len(words), len(WORDS))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0], attempts_before)


if __name__ == "__main__":
    unittest.main()
