#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 시험 출제, 채점, 문항 단위 이력 저장 (VOCA-FR-021~026)
# 파일 위치: src/exam_service.py
#
# 시험 상태는 메모리가 아니라 exam_session, exam_item 테이블에 둔다.
# 서버를 재시작해도 끝나지 않은 시험을 그대로 이어 풀 수 있다.

import json
import random
from datetime import date, datetime, timedelta

FORM_CHOICE = "choice"   # 4지선다
FORM_SHORT = "short"     # 단답형
FORM_OX = "ox"           # OX
FORMS = (FORM_CHOICE, FORM_SHORT, FORM_OX)
DIRECTION_EN_TO_KO = "en2ko"
DIRECTION_KO_TO_EN = "ko2en"
DIRECTIONS = (DIRECTION_EN_TO_KO, DIRECTION_KO_TO_EN)
MIX = "mix"
COUNT_RANGE = (1, 50)
CHOICE_COUNT = 4
RECENT_DAYS = 7          # 이 기간 안에 본 단어는 가중치를 낮춘다


class ExamError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 시험 오류"""


def _timestamp(today):
    return f"{today}T{datetime.now().strftime('%H:%M:%S')}"


def _normalize_answer(text):
    """단답 비교용: 앞뒤 공백 제거, 연속 공백 하나로, 소문자."""
    return " ".join((text or "").strip().lower().split())


def _rate(correct, total):
    if not total:
        return None
    return round(correct * 100.0 / total, 1)


def _load_pool(conn, user_id, today):
    """모든 단어와 이 계정의 시험 이력(틀린 횟수, 마지막 출제일)을 함께 읽는다."""
    cutoff = (date.fromisoformat(today) - timedelta(days=RECENT_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT w.id, w.english, w.meaning, "
        "(SELECT COUNT(*) FROM exam_item ei JOIN exam_session es ON es.id = ei.exam_id "
        "   WHERE es.user_id = ? AND ei.word_id = w.id) AS tested, "
        "(SELECT COUNT(*) FROM exam_item ei JOIN exam_session es ON es.id = ei.exam_id "
        "   WHERE es.user_id = ? AND ei.word_id = w.id AND ei.is_correct = 0) AS wrong, "
        "(SELECT MAX(substr(ei.answered_at, 1, 10)) FROM exam_item ei JOIN exam_session es ON es.id = ei.exam_id "
        "   WHERE es.user_id = ? AND ei.word_id = w.id) AS last_tested "
        "FROM word w ORDER BY w.id",
        (user_id, user_id, user_id),
    ).fetchall()
    pool = []
    for row in rows:
        weight = 1
        if row["tested"] == 0:
            weight += 2                      # 시험 본 적 없는 단어
        if row["wrong"] > 0:
            weight += 3                      # 자주 틀린 단어
        if row["last_tested"] and row["last_tested"] < cutoff:
            weight += 1                      # 오래 전에 본 단어
        pool.append({"id": row["id"], "english": row["english"], "meaning": row["meaning"], "weight": weight})
    return pool


def _weighted_sample(pool, count, rng):
    """가중치에 따라 중복 없이 count개를 고른다 (VOCA-FR-022)."""
    remaining = list(pool)
    chosen = []
    for _ in range(count):
        total = sum(item["weight"] for item in remaining)
        pick = rng.uniform(0, total)
        upto = 0
        for index, item in enumerate(remaining):
            upto += item["weight"]
            if pick <= upto:
                chosen.append(remaining.pop(index))
                break
    return chosen


def _build_item(word, direction, form, meanings, englishes, rng, position):
    """문항 하나를 만든다. 정답과 보기를 여기서 정해 DB에 그대로 저장한다."""
    if direction == DIRECTION_EN_TO_KO:
        prompt, correct, values = word["english"], word["meaning"], meanings
    else:
        prompt, correct, values = word["meaning"], word["english"], englishes
    other_values = [value for value in values if value != correct]
    options = None
    correct_answer = correct
    if form == FORM_CHOICE:
        options = rng.sample(other_values, CHOICE_COUNT - 1) + [correct]
        rng.shuffle(options)
    elif form == FORM_OX:
        if rng.random() < 0.5:
            shown, correct_answer = correct, "O"
        else:
            shown, correct_answer = rng.choice(other_values), "X"
        options = [shown]
    return {
        "position": position,
        "word_id": word["id"],
        "direction": direction,
        "form": form,
        "prompt": prompt,
        "options_json": json.dumps(options, ensure_ascii=False) if options is not None else None,
        "correct_answer": correct_answer,
    }


def create_exam(conn, user_id, count, direction, form, today, rng=None):
    """시험을 만들고 exam_id를 돌려준다 (VOCA-FR-021, 023, 024)."""
    rng = rng or random
    low, high = COUNT_RANGE
    if not isinstance(count, int) or not low <= count <= high:
        raise ExamError(f"문제 수는 {low}~{high} 사이로 고르세요.")
    if direction not in DIRECTIONS + (MIX,):
        raise ExamError("출제 방향을 확인하세요.")
    if form not in FORMS + (MIX,):
        raise ExamError("출제 형식을 확인하세요.")
    pool = _load_pool(conn, user_id, today)
    if len(pool) < count:
        raise ExamError(f"시험을 보려면 단어가 {count}개 이상 있어야 합니다. (현재 {len(pool)}개)")
    meanings = sorted({row["meaning"] for row in conn.execute("SELECT meaning FROM word")})
    englishes = sorted({row["english"] for row in conn.execute("SELECT english FROM word")})
    if len(meanings) < CHOICE_COUNT:
        raise ExamError("시험을 보려면 서로 다른 뜻의 단어가 4개 이상 필요합니다.")
    items = []
    for position, word in enumerate(_weighted_sample(pool, count, rng), start=1):
        item_direction = rng.choice(DIRECTIONS) if direction == MIX else direction
        item_form = rng.choice(FORMS) if form == MIX else form
        items.append(_build_item(word, item_direction, item_form, meanings, englishes, rng, position))
    with conn:
        cursor = conn.execute(
            "INSERT INTO exam_session (user_id, started_at, question_count, direction, form) VALUES (?, ?, ?, ?, ?)",
            (user_id, _timestamp(today), count, direction, form),
        )
        exam_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO exam_item (exam_id, position, word_id, direction, form, prompt, options_json, correct_answer) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    exam_id,
                    item["position"],
                    item["word_id"],
                    item["direction"],
                    item["form"],
                    item["prompt"],
                    item["options_json"],
                    item["correct_answer"],
                )
                for item in items
            ],
        )
    return exam_id


def get_exam(conn, user_id, exam_id):
    """이 계정의 시험만 돌려준다. 다른 계정 시험이면 찾을 수 없다고 한다."""
    row = conn.execute(
        "SELECT id, user_id, started_at, finished_at, question_count, direction, form "
        "FROM exam_session WHERE id = ? AND user_id = ?",
        (exam_id, user_id),
    ).fetchone()
    if row is None:
        raise ExamError("시험을 찾을 수 없습니다.")
    return row


def unfinished_exam_id(conn, user_id):
    row = conn.execute(
        "SELECT id FROM exam_session WHERE user_id = ? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return row[0] if row else None


def current_item(conn, exam_id):
    """아직 답하지 않은 첫 문항. 모두 답했으면 None."""
    row = conn.execute(
        "SELECT * FROM exam_item WHERE exam_id = ? AND answered_at IS NULL ORDER BY position LIMIT 1",
        (exam_id,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["options"] = json.loads(item["options_json"]) if item["options_json"] else None
    total = conn.execute("SELECT COUNT(*) FROM exam_item WHERE exam_id = ?", (exam_id,)).fetchone()[0]
    item["number"] = item["position"]
    item["total"] = total
    return item


def _grade(form, correct_answer, answer):
    if form == FORM_SHORT:
        return _normalize_answer(answer) == _normalize_answer(correct_answer)
    if form == FORM_OX:
        return (answer or "").strip().upper() == correct_answer
    return answer == correct_answer


def answer_item(conn, user_id, exam_id, item_id, answer, today):
    """현재 문항에 답하고 채점한다. 마지막 문항이면 시험을 끝낸다 (VOCA-FR-026)."""
    exam = get_exam(conn, user_id, exam_id)
    if exam["finished_at"] is not None:
        raise ExamError("이미 끝난 시험입니다.")
    current = current_item(conn, exam_id)
    if current is None or current["id"] != item_id:
        raise ExamError("현재 문항이 아닙니다. 다시 확인하세요.")
    is_correct = _grade(current["form"], current["correct_answer"], answer)
    with conn:
        conn.execute(
            "UPDATE exam_item SET selected_answer = ?, is_correct = ?, answered_at = ? WHERE id = ?",
            (answer or "", int(is_correct), _timestamp(today), item_id),
        )
        if current_item(conn, exam_id) is None:
            conn.execute(
                "UPDATE exam_session SET finished_at = ? WHERE id = ?",
                (_timestamp(today), exam_id),
            )
    return {
        "is_correct": is_correct,
        "correct_answer": current["correct_answer"],
        "finished": current_item(conn, exam_id) is None,
    }


def exam_result(conn, user_id, exam_id):
    """채점 결과 화면용 요약. 끝난 시험만 돌려준다 (VOCA-FR-025)."""
    exam = get_exam(conn, user_id, exam_id)
    rows = conn.execute(
        "SELECT position, prompt, direction, form, correct_answer, selected_answer, is_correct "
        "FROM exam_item WHERE exam_id = ? ORDER BY position",
        (exam_id,),
    ).fetchall()
    items = [dict(row) for row in rows]
    answered = [item for item in items if item["is_correct"] is not None]
    correct = sum(item["is_correct"] for item in answered)
    return {
        "exam_id": exam_id,
        "finished": exam["finished_at"] is not None,
        "total": len(items),
        "answered": len(answered),
        "correct": correct,
        "rate": _rate(correct, len(answered)),
        "wrong_items": [item for item in answered if not item["is_correct"]],
        "items": items,
        "direction": exam["direction"],
        "form": exam["form"],
        "started_at": exam["started_at"],
    }
