#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 브라우저 점검용 임시 DB 준비 (실제 data/smartvoca.db는 건드리지 않음)
# 파일 위치: ai-agent/claude/261125_화면점검/script/seed_check_db.py
#
# 사용법: python seed_check_db.py <임시 DB 경로>
#   - 회원 tester (비밀번호 password123) 생성
#   - 기초 단어 100개 가져오기
#   - 학습 세션을 한 번 끝내되 처음 3문제는 틀림 (자주 틀린 단어, 학습 기록 표시용)
#   - 시험 1회를 끝까지 풀되 절반만 맞힘 (시험 추이 표시용)

import random
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT / "src"))

import auth_service  # noqa: E402
import db  # noqa: E402
import exam_service  # noqa: E402
import study_service  # noqa: E402
import word_service  # noqa: E402

USER_ID = 1


def run_study_session(conn, today, rng):
    active = study_service.resume_or_start_session(conn, USER_ID, today)
    answered = 0
    while True:
        question = study_service.current_question(conn, active, rng)
        if question is None:
            break
        selected = question["correct_meaning"]
        if answered < 3:
            selected = next(option for option in question["options"] if option != question["correct_meaning"])
        result = study_service.submit_answer(conn, USER_ID, question["word_id"], selected, today)
        answered += 1
        if result["session_finished"]:
            break


def run_exam(conn, today, rng):
    exam_id = exam_service.create_exam(conn, USER_ID, 6, "en2ko", "choice", today, rng)
    for index in range(6):
        item = exam_service.current_item(conn, exam_id)
        answer = item["correct_answer"] if index % 2 == 0 else "틀린 답"
        exam_service.answer_item(conn, USER_ID, exam_id, item["id"], answer, today)


def main(db_path):
    today = date.today().isoformat()
    rng = random.Random(20261125)
    conn = db.connect(db_path)
    auth_service.create_user(conn, "tester", "password123", "password123")
    word_service.import_words_csv(conn, (PROJECT / "data" / "words_public.csv").read_bytes())
    run_study_session(conn, today, rng)
    run_exam(conn, today, rng)
    conn.close()
    print(f"seeded: {db_path}")


if __name__ == "__main__":
    main(sys.argv[1])
