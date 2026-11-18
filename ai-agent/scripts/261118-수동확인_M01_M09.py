#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-18 - 스마트보카 - 테스트 정의서 M-01~M-09 화면 흐름을 Flask 테스트 클라이언트로 점검 (1회성)
# 파일 위치: ai-agent/scripts/261118-수동확인_M01_M09.py
#
# 사용법: python ai-agent/scripts/261118-수동확인_M01_M09.py
# 임시 폴더의 DB만 쓰므로 data/smartvoca.db 는 건드리지 않는다.
# 브라우저에서만 보이는 항목(키 입력, 확인 창)은 코드 검사로 대신하고 '부분'으로 표시한다.

import re
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import app as smartvoca_app  # noqa: E402
import db  # noqa: E402
import study_service  # noqa: E402

WORDS = [("apple", "사과"), ("banana", "바나나"), ("cherry", "체리"), ("grape", "포도"), ("lemon", "레몬")]
results = []


def record(item, status, detail):
    results.append((item, status, detail))


def strip_flash(html):
    """알림 줄은 세션에 남았다가 다음 화면에 나오므로 화면 비교에서 뺀다."""
    return re.sub(r'<p class="flash[^"]*">.*?</p>', "", html)


def current_question(conn):
    return study_service.current_question(conn, study_service._active)


def answer_rest_of_session(client, conn, first_wrong):
    """세션을 끝까지 푼다. 첫 문제만 오답으로 고를 수 있고 나머지는 모두 정답이다. 마지막 응답을 돌려준다."""
    last = None
    first = True
    while True:
        question = current_question(conn)
        if question is None:
            break
        meaning = question["correct_meaning"]
        if first and first_wrong:
            meaning = next(option for option in question["options"] if option != question["correct_meaning"])
        first = False
        last = client.post(
            "/api/study/answer",
            json={"word_id": question["word_id"], "selected_meaning": meaning},
        ).get_json()
        if last["session_finished"]:
            break
    return last


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "check.db")
        conn = db.connect(db_path)
        study_service.reset_state()
        client = smartvoca_app.create_app(db_path).test_client()

        # M-01: 단어 4개 미만이면 안내와 등록 버튼이 나오고, 뜻이 다른 단어 5개면 학습 시작 버튼이 나온다
        for english, meaning in WORDS[:3]:
            client.post("/words", data={"english": english, "meaning": meaning})
        home_few = client.get("/").get_data(as_text=True)
        for english, meaning in WORDS[3:]:
            client.post("/words", data={"english": english, "meaning": meaning})
        home_ready = client.get("/").get_data(as_text=True)
        ok_m01 = (
            "서로 다른 뜻의 단어를 4개 이상 등록해야" in home_few
            and "단어 등록하기" in home_few
            and "학습 시작 →" in home_ready
            and "서로 다른 뜻의 단어를 4개 이상 등록해야" not in home_ready
        )
        record("M-01", "통과" if ok_m01 else "실패", "4개 미만: 안내와 등록 버튼 / 5개: 학습 시작 버튼")

        # M-07: 같은 영어 단어를 다시 등록하면 중복 알림이 나온다 (대소문자와 공백은 무시)
        dup_text = client.post(
            "/words", data={"english": "Apple ", "meaning": "사과"}, follow_redirects=True
        ).get_data(as_text=True)
        ok_m07 = "! 이미 등록된 단어입니다." in dup_text
        record("M-07", "통과" if ok_m07 else "실패", "중복 등록 시 '! 이미 등록된 단어입니다.' 표시")

        # M-06: 수정과 삭제 메시지, 삭제 확인 문구
        words_page = client.get("/words").get_data(as_text=True)
        ok_confirm = "관련 학습 기록도 함께 삭제됩니다" in words_page
        edited = client.post(
            "/words/1/edit", data={"english": "apple", "meaning": "사과(과일)", "example": ""},
            follow_redirects=True,
        ).get_data(as_text=True)
        deleted = client.post("/words/5/delete", follow_redirects=True).get_data(as_text=True)
        ok_m06 = ok_confirm and "✓ 단어를 수정했습니다." in edited and "✓ 단어를 삭제했습니다." in deleted
        record("M-06", "부분" if ok_m06 else "실패", "등록·수정·삭제 메시지와 삭제 확인 문구 확인. 확인 창 팝업은 브라우저 미확인")

        # M-08: 기록이 없으면 안내가 나온다 (아직 아무 학습도 하지 않은 상태)
        report_empty = client.get("/report").get_data(as_text=True)
        ok_m08 = "아직 학습 기록이 없습니다" in report_empty
        record("M-08", "통과" if ok_m08 else "실패", "기록 없음 문구 확인")

        # M-02: 답 제출 응답의 서버 처리 시간 (브라우저 표시 시간은 측정하지 않음)
        client.get("/study")
        question = current_question(conn)
        started = time.perf_counter()
        first = client.post(
            "/api/study/answer",
            json={"word_id": question["word_id"], "selected_meaning": question["correct_meaning"]},
        )
        elapsed = time.perf_counter() - started
        ok_m02 = first.status_code == 200 and elapsed < 1.0
        record("M-02", "부분" if ok_m02 else "실패", f"서버 응답 {elapsed * 1000:.1f} ms. 브라우저 표시 시간은 미측정")

        # M-04: 오답이면 정답이 응답에 담기고, 그 단어가 블록 끝에 다시 들어간다
        study_service.reset_state()
        client.get("/study")
        question = current_question(conn)
        wrong = next(option for option in question["options"] if option != question["correct_meaning"])
        reply = client.post(
            "/api/study/answer", json={"word_id": question["word_id"], "selected_meaning": wrong}
        ).get_json()
        queue_after = study_service._active.blocks[0].queue
        ok_m04 = (
            reply["correct"] is False
            and reply["correct_meaning"] == question["correct_meaning"]
            and queue_after[-1] == question["word_id"]
        )
        record("M-04", "통과" if ok_m04 else "실패", "오답 응답에 정답 포함, 같은 단어가 블록 끝에 재배치")

        # M-03: 숫자 키 1~4 처리 코드 확인 (실제 키 입력은 브라우저 미확인)
        study_html = (PROJECT_ROOT / "src" / "templates" / "study.html").read_text(encoding="utf-8")
        ok_m03 = "/^[1-4]$/.test(event.key)" in study_html
        record("M-03", "부분" if ok_m03 else "실패", "키 1~4 처리 코드 확인. 실제 키 입력은 브라우저 미확인")

        # M-05: 마지막 문제의 응답에 session_finished가 오고, 완료 화면이 나온다
        last = answer_rest_of_session(client, conn, first_wrong=False)
        done = client.get("/study/done").get_data(as_text=True)
        ok_m05 = last is not None and last["session_finished"] and "오늘의 학습 완료" in done
        record("M-05", "통과" if ok_m05 else "실패", "마지막 응답 session_finished 후 완료 화면 표시")

        # M-09: 앱을 새로 만들어도(같은 DB) 기록과 홈 통계가 그대로다
        report_before = strip_flash(client.get("/report").get_data(as_text=True))
        home_before = strip_flash(client.get("/").get_data(as_text=True))
        study_service.reset_state()
        restarted = smartvoca_app.create_app(db_path).test_client()
        report_after = strip_flash(restarted.get("/report").get_data(as_text=True))
        home_after = strip_flash(restarted.get("/").get_data(as_text=True))
        ok_m09 = report_before == report_after and home_before == home_after and "학습 기록" in report_after
        record("M-09", "통과" if ok_m09 else "실패", "재시작(새 앱, 같은 DB) 후 기록 화면과 홈 화면 동일")

        conn.close()

    for item, status, detail in results:
        print(f"{item}\t{status}\t{detail}")


if __name__ == "__main__":
    main()
