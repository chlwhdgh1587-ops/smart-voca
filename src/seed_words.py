#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 공개 단어 목록(CSV)을 DB에 1회 적재 (NFR-05)
# 파일 위치: src/seed_words.py
#
# 사용법: python src/seed_words.py [CSV 경로]
# CSV 열: english, meaning (UTF-8)

import csv
import sys
from pathlib import Path

import db
import word_service

DEFAULT_CSV_PATH = db.PROJECT_ROOT / "data" / "words_public.csv"


def load_words(conn, csv_path):
    """CSV를 읽어 단어를 등록하고 (등록 수, 중복 건너뜀 수, 잘못된 행 수)를 돌려준다."""
    added = skipped = invalid = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            try:
                word_service.add_word(conn, row.get("english", ""), row.get("meaning", ""))
                added += 1
            except word_service.DuplicateWordError:
                skipped += 1
            except word_service.WordError:
                invalid += 1
    return added, skipped, invalid


def main(argv):
    csv_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_CSV_PATH
    if not csv_path.exists():
        print(f"단어 목록 파일이 없습니다: {csv_path}")
        return 1
    conn = db.connect()
    added, skipped, invalid = load_words(conn, csv_path)
    print(f"등록 {added}개, 중복 건너뜀 {skipped}개, 잘못된 행 {invalid}개")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
