#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 시험 출제, 채점, 문항 이력 단위 테스트 (VOCA-FR-021~026)
# 파일 위치: tests/test_exam_service.py

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import exam_service  # noqa: E402
import word_service  # noqa: E402

USER = 1
TODAY = "2026-10-21"
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


class ExamServiceTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(db.MEMORY_DB)
        for english, meaning in WORDS:
            word_service.add_word(self.conn, english, meaning)
        self.rng = random.Random(7)

    def tearDown(self):
        self.conn.close()

    def items(self, exam_id):
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM exam_item WHERE exam_id = ? ORDER BY position", (exam_id,)
        )]

    def word_row(self, english):
        return self.conn.execute("SELECT * FROM word WHERE english = ?", (english,)).fetchone()

    def test_choice_items_have_four_options_including_answer(self):
        # FR-024: 4지선다 보기는 4개이고 정답을 포함한다
        exam_id = exam_service.create_exam(self.conn, USER, 5, "en2ko", "choice", TODAY, self.rng)
        for item in self.items(exam_id):
            options = exam_service.json.loads(item["options_json"])
            self.assertEqual(len(options), 4)
            self.assertIn(item["correct_answer"], options)

    def test_mix_creates_only_valid_directions_and_forms(self):
        # FR-023, FR-024: 섞기는 방향과 형식을 각 문항마다 고른다
        exam_id = exam_service.create_exam(self.conn, USER, 8, "mix", "mix", TODAY, self.rng)
        for item in self.items(exam_id):
            self.assertIn(item["direction"], ("en2ko", "ko2en"))
            self.assertIn(item["form"], ("choice", "short", "ox"))

    def test_ox_answer_is_graded_by_letter(self):
        # FR-024: OX 문항은 제시된 뜻이 맞으면 O, 틀리면 X
        exam_id = exam_service.create_exam(self.conn, USER, 1, "en2ko", "ox", TODAY, self.rng)
        item = exam_service.current_item(self.conn, exam_id)
        right = item["correct_answer"]
        wrong = "X" if right == "O" else "O"
        result = exam_service.answer_item(self.conn, USER, exam_id, item["id"], right, TODAY)
        self.assertTrue(result["is_correct"])
        self.assertTrue(result["finished"])
        self.assertEqual(self.items(exam_id)[0]["is_correct"], 1)
        self.assertNotEqual(wrong, right)

    def test_short_answer_ignores_case_and_extra_spaces(self):
        # FR-024: 단답형은 대소문자와 앞뒤 공백을 무시한다
        exam_id = exam_service.create_exam(self.conn, USER, 1, "ko2en", "short", TODAY, self.rng)
        item = exam_service.current_item(self.conn, exam_id)
        english = item["correct_answer"]
        result = exam_service.answer_item(
            self.conn, USER, exam_id, item["id"], f"  {english.upper()}  ", TODAY
        )
        self.assertTrue(result["is_correct"])

    def test_exam_result_lists_wrong_items_and_score(self):
        # FR-025, FR-026: 채점 결과와 문항 이력
        exam_id = exam_service.create_exam(self.conn, USER, 2, "en2ko", "choice", TODAY, self.rng)
        first = exam_service.current_item(self.conn, exam_id)
        wrong_answer = next(option for option in exam_service.json.loads(first["options_json"])
                            if option != first["correct_answer"])
        exam_service.answer_item(self.conn, USER, exam_id, first["id"], wrong_answer, TODAY)
        second = exam_service.current_item(self.conn, exam_id)
        finished = exam_service.answer_item(self.conn, USER, exam_id, second["id"], second["correct_answer"], TODAY)
        self.assertTrue(finished["finished"])
        result = exam_service.exam_result(self.conn, USER, exam_id)
        self.assertTrue(result["finished"])
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["wrong_items"]), 1)
        self.assertEqual(result["wrong_items"][0]["selected_answer"], wrong_answer)

    def test_answer_must_be_current_item(self):
        # 문항은 순서대로만 답한다
        exam_id = exam_service.create_exam(self.conn, USER, 2, "en2ko", "short", TODAY, self.rng)
        later = self.items(exam_id)[1]
        with self.assertRaises(exam_service.ExamError):
            exam_service.answer_item(self.conn, USER, exam_id, later["id"], "x", TODAY)

    def test_other_account_cannot_open_exam(self):
        # 계정별 분리: 다른 계정의 시험은 찾을 수 없다고 응답한다
        exam_id = exam_service.create_exam(self.conn, USER, 1, "en2ko", "short", TODAY, self.rng)
        with self.assertRaises(exam_service.ExamError):
            exam_service.get_exam(self.conn, 2, exam_id)

    def test_too_many_questions_is_rejected(self):
        # 단어가 모자라면 출제하지 않는다 (VOCA-FR-021)
        with self.assertRaises(exam_service.ExamError):
            exam_service.create_exam(self.conn, USER, 9, "en2ko", "choice", TODAY, self.rng)

    def test_wrong_history_raises_selection_weight(self):
        # VOCA-FR-022: 자주 틀린 단어는 더 자주 뽑힌다
        exam_id = exam_service.create_exam(self.conn, USER, 1, "en2ko", "short", TODAY, self.rng)
        item = exam_service.current_item(self.conn, exam_id)
        exam_service.answer_item(self.conn, USER, exam_id, item["id"], "틀린 답", TODAY)
        wrong_word_id = item["word_id"]
        pool = {row["id"]: row["weight"] for row in exam_service._load_pool(self.conn, USER, TODAY)}
        untested_weight = min(w for word_id, w in pool.items() if word_id != wrong_word_id)
        self.assertGreater(pool[wrong_word_id], untested_weight)


if __name__ == "__main__":
    unittest.main()
