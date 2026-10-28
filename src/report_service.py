#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 학습 기록 집계 (FR-04)
# 파일 위치: src/report_service.py

from study_service import BLOCK_NEW, MASTERY_STREAK


def _rate(correct, attempts):
    """정답률을 백분율로 돌려준다. 기록이 없으면 None."""
    if not attempts:
        return None
    return round(correct * 100.0 / attempts, 1)


def daily_summary(conn):
    """날짜별 학습 단어 수와 정답률 (FR-04.1, FR-04.2)"""
    rows = conn.execute(
        "SELECT substr(attempted_at, 1, 10) AS study_date, "
        "COUNT(DISTINCT CASE WHEN block = ? THEN word_id END) AS learned_count, "
        "COUNT(*) AS attempt_count, "
        "SUM(is_correct) AS correct_count "
        "FROM attempt GROUP BY study_date ORDER BY study_date DESC",
        (BLOCK_NEW,),
    ).fetchall()
    return [
        {
            "date": row["study_date"],
            "learned": row["learned_count"],
            "attempts": row["attempt_count"],
            "rate": _rate(row["correct_count"] or 0, row["attempt_count"]),
        }
        for row in rows
    ]


def session_summary(conn, session_id):
    """세션 완료 화면용 요약 (FR-04.2, FR-04.3)"""
    row = conn.execute(
        "SELECT COUNT(DISTINCT CASE WHEN block = ? THEN word_id END) AS learned_count, "
        "COUNT(*) AS attempt_count, "
        "SUM(is_correct) AS correct_count "
        "FROM attempt WHERE session_id = ?",
        (BLOCK_NEW, session_id),
    ).fetchone()
    attempts = row["attempt_count"]
    return {
        "learned": row["learned_count"],
        "attempts": attempts,
        "rate": _rate(row["correct_count"] or 0, attempts),
    }


def mastery_summary(conn):
    """완벽 암기 단어 수와 복습 대기 단어 수 (FR-04.3)"""
    mastered = conn.execute(
        "SELECT COUNT(*) FROM word_state WHERE consecutive_correct >= ?",
        (MASTERY_STREAK,),
    ).fetchone()[0]
    review_pending = conn.execute(
        "SELECT COUNT(*) FROM word_state WHERE in_review = 1"
    ).fetchone()[0]
    return {"mastered": mastered, "review_pending": review_pending}
