#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 계정별 설정 저장과 검증 (VOCA-FR-011, VOCA-FR-061·062)
# 파일 위치: src/settings_service.py

DEFAULT_SETTINGS = {
    "daily_target": 20,      # 하루 신규 단어 수
    "review_ratio": 100,     # 복습 대상 중 오늘 낼 비율(%). 100이면 전부 낸다
    "exam_count": 10,        # 시험 기본 문제 수
    "exam_direction": "mix",  # en2ko, ko2en, mix
    "exam_form": "mix",       # choice, short, ox, mix
}

DAILY_TARGET_RANGE = (5, 50)
REVIEW_RATIOS = (50, 100)
EXAM_COUNTS = (5, 10, 20)
EXAM_DIRECTIONS = ("en2ko", "ko2en", "mix")
EXAM_FORMS = ("choice", "short", "ox", "mix")


class SettingError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 설정 오류"""


def get_settings(conn, user_id):
    """계정의 설정을 돌려준다. 저장된 값이 없으면 기본값을 쓴다."""
    row = conn.execute(
        "SELECT daily_target, review_ratio, exam_count, exam_direction, exam_form "
        "FROM user_setting WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return dict(DEFAULT_SETTINGS)
    return dict(row)


def _parse_choice(raw, allowed, message):
    try:
        value = int(raw) if isinstance(allowed[0], int) else str(raw)
    except (TypeError, ValueError) as error:
        raise SettingError(message) from error
    if value not in allowed:
        raise SettingError(message)
    return value


def validate_settings(values):
    """입력 값을 검증해 저장할 형태로 바꾼다. 잘못된 값이면 SettingError."""
    low, high = DAILY_TARGET_RANGE
    try:
        daily_target = int(values.get("daily_target"))
    except (TypeError, ValueError) as error:
        raise SettingError("하루 학습량은 숫자로 입력하세요.") from error
    if not low <= daily_target <= high:
        raise SettingError(f"하루 학습량은 {low}~{high} 사이로 입력하세요.")
    return {
        "daily_target": daily_target,
        "review_ratio": _parse_choice(values.get("review_ratio"), REVIEW_RATIOS, "복습 비율을 확인하세요."),
        "exam_count": _parse_choice(values.get("exam_count"), EXAM_COUNTS, "시험 문제 수를 확인하세요."),
        "exam_direction": _parse_choice(values.get("exam_direction"), EXAM_DIRECTIONS, "출제 방향을 확인하세요."),
        "exam_form": _parse_choice(values.get("exam_form"), EXAM_FORMS, "출제 형식을 확인하세요."),
    }


def save_settings(conn, user_id, values):
    """검증을 통과한 설정을 저장한다 (VOCA-FR-062)."""
    clean = validate_settings(values)
    with conn:
        conn.execute(
            "INSERT INTO user_setting (user_id, daily_target, review_ratio, exam_count, exam_direction, exam_form) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET daily_target = excluded.daily_target, "
            "review_ratio = excluded.review_ratio, exam_count = excluded.exam_count, "
            "exam_direction = excluded.exam_direction, exam_form = excluded.exam_form",
            (
                user_id,
                clean["daily_target"],
                clean["review_ratio"],
                clean["exam_count"],
                clean["exam_direction"],
                clean["exam_form"],
            ),
        )
    return clean
