#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 단어 검색과 CSV 가져오기 단위 테스트 (VOCA-FR-003, VOCA-FR-004)
# 파일 위치: tests/test_word_import_search.py

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import word_service  # noqa: E402

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "words_public.csv"


class WordSearchImportTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(db.MEMORY_DB)
        word_service.add_word(self.conn, "apple", "사과")
        word_service.add_word(self.conn, "banana", "바나나")

    def tearDown(self):
        self.conn.close()

    def test_search_matches_english_or_meaning(self):
        # FR-004: 영단어 또는 뜻에 포함된 단어를 찾는다 (대소문자 무시)
        self.assertEqual([row["english"] for row in word_service.list_words(self.conn, "APP")], ["apple"])
        self.assertEqual([row["english"] for row in word_service.list_words(self.conn, "바나")], ["banana"])

    def test_search_escapes_wildcards(self):
        # % 와 _ 는 와일드카드가 아니라 문자로 취급한다
        self.assertEqual(word_service.list_words(self.conn, "%"), [])
        self.assertEqual(word_service.list_words(self.conn, "_"), [])

    def test_empty_query_returns_all_words(self):
        self.assertEqual(len(word_service.list_words(self.conn, "  ")), 2)

    def test_import_accepts_bom_and_english_headers(self):
        # FR-003: UTF-8 BOM과 영문 머리글을 받는다
        raw = "﻿english,meaning,example\ncherry,체리,A cherry tree.\ngrape,포도,\n".encode("utf-8")
        result = word_service.import_words_csv(self.conn, raw)
        self.assertEqual(result, {"added": 2, "duplicate": 0, "invalid": 0})
        example = self.conn.execute("SELECT example FROM word WHERE english = 'cherry'").fetchone()[0]
        self.assertEqual(example, "A cherry tree.")

    def test_import_accepts_korean_headers(self):
        raw = "영단어,뜻\nlemon,레몬\n".encode("utf-8")
        self.assertEqual(word_service.import_words_csv(self.conn, raw)["added"], 1)

    def test_import_skips_duplicates_and_invalid_rows(self):
        # FR-003 중복 방침: 기존 단어는 건너뛰고 뜻을 덮어쓰지 않는다
        raw = "english,meaning\napple,애플\n,빈 영어\nkiwi,키위\n".encode("utf-8")
        result = word_service.import_words_csv(self.conn, raw)
        self.assertEqual(result, {"added": 1, "duplicate": 1, "invalid": 1})
        meaning = self.conn.execute("SELECT meaning FROM word WHERE english = 'apple'").fetchone()[0]
        self.assertEqual(meaning, "사과")

    def test_import_rejects_missing_columns(self):
        with self.assertRaises(word_service.WordError):
            word_service.import_words_csv(self.conn, "word,mean\nx,y\n".encode("utf-8"))

    def test_import_rejects_non_utf8(self):
        with self.assertRaises(word_service.WordError):
            word_service.import_words_csv(self.conn, b"\xff\xfe\x00bad")

    def test_import_bundled_sample_file(self):
        # 저장소에 들어 있는 기초 단어 파일이 그대로 가져와진다
        raw = SAMPLE_CSV.read_bytes()
        result = word_service.import_words_csv(self.conn, raw)
        self.assertEqual(result["invalid"], 0)
        self.assertGreater(result["added"], 90)


if __name__ == "__main__":
    unittest.main()
