#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-18 - 스마트보카 - 복습 완료 문구를 화면에서 확인하도록 임시 DB로 앱 실행 (1회성)
# 파일 위치: ai-agent/scripts/261118-복습완료_임시DB.py
#
# 사용법: python ai-agent/scripts/261118-복습완료_임시DB.py
# 임시 폴더에 단어 5개짜리 DB를 새로 만들고, apple 하나만 복습 대상(연속 정답 2)으로 둔다.
# 브라우저에서 http://127.0.0.1:5000/study 를 열면 첫 문제가 apple(복습)이다. 뜻 "사과"를 고르면
# "정답입니다! 복습이 끝났습니다"가 나와야 한다. 실제 data/smartvoca.db 는 건드리지 않는다.
# 끝내려면 이 창에서 Ctrl+C.

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import app as smartvoca_app  # noqa: E402

WORDS = [("apple", "사과"), ("banana", "바나나"), ("cherry", "체리"), ("grape", "포도"), ("lemon", "레몬")]


def build_db(db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    client = smartvoca_app.create_app(db_path).test_client()
    for english, meaning in WORDS:
        client.post("/words", data={"english": english, "meaning": meaning})
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE word_state SET consecutive_correct = 2, first_studied_on = '2026-11-10', "
        "last_studied_on = '2026-11-17', in_review = 1 "
        "WHERE word_id = (SELECT id FROM word WHERE english = 'apple')"
    )
    conn.commit()
    conn.close()


def main():
    db_dir = Path(tempfile.gettempdir()) / "smartvoca_manual"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(db_dir / "review_check.db")
    build_db(db_path)
    print(f"임시 DB: {db_path}")
    print("브라우저에서 http://127.0.0.1:5000/study 를 여세요. 끝내려면 Ctrl+C.")
    smartvoca_app.create_app(db_path).run(host="127.0.0.1", port=5000, debug=False, threaded=False)


if __name__ == "__main__":
    main()
