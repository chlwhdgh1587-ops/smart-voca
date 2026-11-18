#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 학습 세션 단위 테스트 (FR-02, FR-03)
# 파일 위치: tests/test_study_service.py

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import study_service  # noqa: E402
import word_service  # noqa: E402

WORDS = [
    ("apple", "사과"),
    ("banana", "바나나"),
    ("cherry", "체리"),
    ("grape", "포도"),
    ("lemon", "레몬"),
]
DAY1 = "2026-10-21"
DAY2 = "2026-10-22"


class StudyServiceTest(unittest.TestCase):
    def setUp(self):
        study_service.reset_state()
        self.conn = db.connect(db.MEMORY_DB)
        self.rng = random.Random(7)

    def tearDown(self):
        study_service.reset_state()
        self.conn.close()

    def add_words(self, words=WORDS):
        for english, meaning in words:
            word_service.add_word(self.conn, english, meaning)

    def word_id(self, english):
        row = self.conn.execute("SELECT id FROM word WHERE english = ?", (english,)).fetchone()
        return row[0]

    def state(self, english):
        return self.conn.execute(
            "SELECT consecutive_correct, first_studied_on, in_review FROM word_state WHERE word_id = ?",
            (self.word_id(english),),
        ).fetchone()

    def answer_all_correctly(self, active, today):
        """세션이 끝날 때까지 모든 문제를 맞힌다."""
        while True:
            question = study_service.current_question(self.conn, active, self.rng)
            if question is None:
                return
            result = study_service.submit_answer(
                self.conn, question["word_id"], question["correct_meaning"], today
            )
            self.assertTrue(result["correct"])
            if result["session_finished"]:
                return

    def test_start_requires_four_words(self):
        # FR-02.2: 보기 4개를 만들 수 없으면 학습을 시작하지 않는다 (ADR-004)
        self.add_words(WORDS[:3])
        with self.assertRaises(study_service.StudyError):
            study_service.resume_or_start_session(self.conn, DAY1)

    def test_start_requires_four_distinct_meanings(self):
        # ADR-004: 뜻이 같은 단어만 4개면 보기를 만들 수 없으므로 시작하지 않는다
        for english in ["apple", "pear", "melon", "peach"]:
            word_service.add_word(self.conn, english, "과일")
        with self.assertRaises(study_service.StudyError):
            study_service.resume_or_start_session(self.conn, DAY1)

    def test_new_block_takes_words_in_registration_order(self):
        # FR-02.1: 미출제 신규 단어를 등록 순서대로 고른다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.assertEqual(len(active.blocks), 1)
        self.assertEqual(active.blocks[0].name, study_service.BLOCK_NEW)
        expected = [self.word_id(english) for english, _ in WORDS]
        self.assertEqual(active.blocks[0].queue, expected)

    def test_new_block_is_capped_at_daily_target(self):
        # FR-02: 하루 신규 목표는 20개
        words = [(f"word{index:02d}", f"뜻{index:02d}") for index in range(25)]
        self.add_words(words)
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.assertEqual(len(active.blocks[0].queue), study_service.DAILY_NEW_TARGET)

    def test_question_has_four_options_with_correct_meaning(self):
        # FR-02.2: 보기 4개, 정답 1 + 오답 3, 정답은 다른 단어의 뜻이 아니다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        question = study_service.current_question(self.conn, active, self.rng)
        self.assertEqual(len(question["options"]), 4)
        self.assertIn(question["correct_meaning"], question["options"])
        self.assertEqual(len(set(question["options"])), 4)

    def test_wrong_answer_is_requeued_and_resets_streak(self):
        # FR-02.3, FR-02.4: 틀리면 같은 블록 끝에 다시 출제되고 연속 정답 수가 0이 된다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        question = study_service.current_question(self.conn, active, self.rng)
        wrong = next(option for option in question["options"] if option != question["correct_meaning"])
        result = study_service.submit_answer(self.conn, question["word_id"], wrong, DAY1)
        self.assertFalse(result["correct"])
        self.assertEqual(active.blocks[0].queue[-1], question["word_id"])
        self.assertEqual(self.state(question["english"])["consecutive_correct"], 0)

    def test_new_block_correct_answer_is_not_repeated(self):
        # FR-02.3: 신규 블록에서 맞힌 단어는 같은 세션에서 다시 나오지 않는다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        question = study_service.current_question(self.conn, active, self.rng)
        study_service.submit_answer(self.conn, question["word_id"], question["correct_meaning"], DAY1)
        self.assertNotIn(question["word_id"], active.blocks[0].queue)

    def test_review_block_repeats_until_three_in_a_row(self):
        # FR-03.2: 복습 블록에서는 연속 3회 정답에 도달할 때까지 반복한다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.answer_all_correctly(active, DAY1)
        self.assertEqual(self.state("apple")["consecutive_correct"], 1)

        active = study_service.resume_or_start_session(self.conn, DAY2)
        self.assertEqual(active.blocks[0].name, study_service.BLOCK_REVIEW)
        self.answer_all_correctly(active, DAY2)

        for english, _ in WORDS:
            self.assertEqual(self.state(english)["consecutive_correct"], 3)

    def test_review_answer_flags_continue_until_third_in_a_row(self):
        # FR-03.2: 복습 블록에서 맞혀도 연속 3회 전까지는 안내 플래그가 켜진다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.answer_all_correctly(active, DAY1)
        active = study_service.resume_or_start_session(self.conn, DAY2)
        while True:
            question = study_service.current_question(self.conn, active, self.rng)
            if question is None:
                break
            streak_before = self.state(question["english"])["consecutive_correct"]
            result = study_service.submit_answer(
                self.conn, question["word_id"], question["correct_meaning"], DAY2
            )
            self.assertEqual(result["review_continues"], streak_before + 1 < study_service.MASTERY_STREAK)
            self.assertEqual(result["review_mastered"], streak_before + 1 >= study_service.MASTERY_STREAK)
            if result["session_finished"]:
                break

    def test_new_block_answer_has_no_review_flag(self):
        # 신규 블록에서는 복습 안내 플래그가 켜지지 않는다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        question = study_service.current_question(self.conn, active, self.rng)
        result = study_service.submit_answer(self.conn, question["word_id"], question["correct_meaning"], DAY1)
        self.assertFalse(result["review_continues"])

    def test_review_targets_are_released_after_review_block(self):
        # FR-03.3: 복습 블록이 끝나면 복습 대상에서 해제된다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.answer_all_correctly(active, DAY1)
        active = study_service.resume_or_start_session(self.conn, DAY2)
        self.answer_all_correctly(active, DAY2)
        for english, _ in WORDS:
            self.assertEqual(self.state(english)["in_review"], 0)

    def test_same_day_restart_does_not_repeat_finished_words(self):
        # 같은 날 세션을 끝낸 뒤 다시 시작하면 신규 단어는 이미 출제되어 나오지 않는다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.answer_all_correctly(active, DAY1)
        study_service.reset_state()
        self.assertIsNone(study_service.resume_or_start_session(self.conn, DAY1))

    def test_restart_closes_unfinished_session_and_keeps_review_targets(self):
        # 프로세스 설계서 1절, 4절 3항: 미완료 세션은 닫고 복습 대상은 유지한다
        self.add_words()
        active = study_service.resume_or_start_session(self.conn, DAY1)
        self.answer_all_correctly(active, DAY1)
        active = study_service.resume_or_start_session(self.conn, DAY2)
        question = study_service.current_question(self.conn, active, self.rng)
        study_service.submit_answer(self.conn, question["word_id"], question["correct_meaning"], DAY2)
        answered_english = question["english"]
        study_service.reset_state()
        restarted = study_service.resume_or_start_session(self.conn, DAY2)
        self.assertNotEqual(restarted.session_id, active.session_id)
        unfinished = self.conn.execute(
            "SELECT COUNT(*) FROM study_session WHERE finished_at IS NULL"
        ).fetchone()[0]
        self.assertEqual(unfinished, 1)
        self.assertEqual(self.state(answered_english)["in_review"], 1)


if __name__ == "__main__":
    unittest.main()
