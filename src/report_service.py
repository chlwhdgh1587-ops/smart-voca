#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 학습 기록 집계 (FR-04)
#   2026-11-25: 계정별 집계, 진도 현황, 시험 추이, 자주 틀린 단어 추가 (VOCA-FR-031~034)
# 파일 위치: src/report_service.py

from study_service import BLOCK_NEW, MASTERY_STREAK, current_day_number


def _rate(correct, attempts):
    """정답률을 백분율로 돌려준다. 기록이 없으면 None."""
    if not attempts:
        return None
    return round(correct * 100.0 / attempts, 1)


def daily_summary(conn, user_id):
    """날짜별 학습 단어 수와 정답률 (FR-04.1, FR-04.2). 일차 번호를 함께 붙인다."""
    rows = conn.execute(
        "SELECT substr(attempted_at, 1, 10) AS study_date, "
        "COUNT(DISTINCT CASE WHEN block = ? THEN word_id END) AS learned_count, "
        "COUNT(*) AS attempt_count, "
        "SUM(is_correct) AS correct_count "
        "FROM attempt WHERE user_id = ? GROUP BY study_date ORDER BY study_date DESC",
        (BLOCK_NEW, user_id),
    ).fetchall()
    new_dates = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT substr(attempted_at, 1, 10) FROM attempt WHERE user_id = ? AND block = ? "
            "ORDER BY 1",
            (user_id, BLOCK_NEW),
        )
    ]
    day_of = {study_date: index for index, study_date in enumerate(new_dates, start=1)}
    return [
        {
            "date": row["study_date"],
            "day": day_of.get(row["study_date"]),
            "learned": row["learned_count"],
            "attempts": row["attempt_count"],
            "rate": _rate(row["correct_count"] or 0, row["attempt_count"]),
        }
        for row in rows
    ]


def session_summary(conn, user_id, session_id):
    """세션 완료 화면용 요약 (FR-04.2, FR-04.3)"""
    row = conn.execute(
        "SELECT COUNT(DISTINCT CASE WHEN block = ? THEN word_id END) AS learned_count, "
        "COUNT(*) AS attempt_count, "
        "SUM(is_correct) AS correct_count "
        "FROM attempt WHERE user_id = ? AND session_id = ?",
        (BLOCK_NEW, user_id, session_id),
    ).fetchone()
    attempts = row["attempt_count"]
    return {
        "learned": row["learned_count"],
        "attempts": attempts,
        "rate": _rate(row["correct_count"] or 0, attempts),
    }


def mastery_summary(conn, user_id):
    """완벽 암기 단어 수와 복습 대기 단어 수 (FR-04.3)"""
    mastered = conn.execute(
        "SELECT COUNT(*) FROM word_state WHERE user_id = ? AND consecutive_correct >= ?",
        (user_id, MASTERY_STREAK),
    ).fetchone()[0]
    review_pending = conn.execute(
        "SELECT COUNT(*) FROM word_state WHERE user_id = ? AND in_review = 1",
        (user_id,),
    ).fetchone()[0]
    return {"mastered": mastered, "review_pending": review_pending}


def progress_summary(conn, user_id, today):
    """진도 현황: 현재 일차, 암기한 단어 수 / 전체 (VOCA-FR-031).

    '암기한 단어'는 연속 3회 정답으로 완벽 암기한 단어로 센다.
    """
    total = conn.execute("SELECT COUNT(*) FROM word").fetchone()[0]
    mastered = mastery_summary(conn, user_id)["mastered"]
    return {
        "day_number": current_day_number(conn, user_id, today),
        "mastered": mastered,
        "total": total,
        "percent": _rate(mastered, total) or 0,
    }


def exam_trend(conn, user_id):
    """시험 성적 추이: 회차별 점수와 날짜별 정답률 (VOCA-FR-032). 끝난 시험만 센다."""
    rows = conn.execute(
        "SELECT es.id, substr(es.started_at, 1, 10) AS exam_date, es.direction, es.form, "
        "COUNT(ei.id) AS total, SUM(CASE WHEN ei.is_correct = 1 THEN 1 ELSE 0 END) AS correct "
        "FROM exam_session es JOIN exam_item ei ON ei.exam_id = es.id "
        "WHERE es.user_id = ? AND es.finished_at IS NOT NULL "
        "GROUP BY es.id ORDER BY es.id",
        (user_id,),
    ).fetchall()
    sessions = [
        {
            "exam_id": row["id"],
            "date": row["exam_date"],
            "direction": row["direction"],
            "form": row["form"],
            "total": row["total"],
            "correct": row["correct"],
            "rate": _rate(row["correct"], row["total"]),
        }
        for row in rows
    ]
    by_date = {}
    for session in sessions:
        bucket = by_date.setdefault(session["date"], {"date": session["date"], "exams": 0, "total": 0, "correct": 0})
        bucket["exams"] += 1
        bucket["total"] += session["total"]
        bucket["correct"] += session["correct"]
    daily = []
    for date_key in sorted(by_date):
        bucket = by_date[date_key]
        bucket["rate"] = _rate(bucket["correct"], bucket["total"])
        daily.append(bucket)
    return {"sessions": sessions, "daily": daily}


def weak_words(conn, user_id, limit=10):
    """자주 틀리는 단어 상위 N개: 암기 답안과 시험 문항의 틀린 횟수를 합쳐 센다 (VOCA-FR-033)."""
    rows = conn.execute(
        "SELECT * FROM ("
        "  SELECT w.id, w.english, w.meaning, "
        "    (SELECT COUNT(*) FROM attempt a WHERE a.user_id = :uid AND a.word_id = w.id AND a.is_correct = 0)"
        "    + (SELECT COUNT(*) FROM exam_item ei JOIN exam_session es ON es.id = ei.exam_id "
        "       WHERE es.user_id = :uid AND ei.word_id = w.id AND ei.is_correct = 0) AS wrong, "
        "    (SELECT COUNT(*) FROM attempt a WHERE a.user_id = :uid AND a.word_id = w.id)"
        "    + (SELECT COUNT(*) FROM exam_item ei JOIN exam_session es ON es.id = ei.exam_id "
        "       WHERE es.user_id = :uid AND ei.word_id = w.id AND ei.is_correct IS NOT NULL) AS attempts "
        "  FROM word w"
        ") WHERE wrong > 0 ORDER BY wrong DESC, id LIMIT :limit",
        {"uid": user_id, "limit": limit},
    ).fetchall()
    return [
        {
            "word_id": row["id"],
            "english": row["english"],
            "meaning": row["meaning"],
            "wrong": row["wrong"],
            "attempts": row["attempts"],
            "rate": _rate(row["attempts"] - row["wrong"], row["attempts"]),
        }
        for row in rows
    ]
