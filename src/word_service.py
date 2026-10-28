#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 단어 등록, 수정, 삭제, 목록 조회 (FR-01)
# 파일 위치: src/word_service.py

import sqlite3
from datetime import datetime


class WordError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 단어 입력 오류"""


class DuplicateWordError(WordError):
    """이미 등록된 영어 단어"""


def normalize_english(english):
    """영어 단어를 앞뒤 공백 제거와 소문자 변환으로 정규화한다 (데이터 설계서 2.1)."""
    normalized = (english or "").strip().lower()
    if not normalized:
        raise WordError("영어 단어를 입력하세요.")
    return normalized


def _require_meaning(meaning):
    cleaned = (meaning or "").strip()
    if not cleaned:
        raise WordError("뜻을 입력하세요.")
    return cleaned


def _optional_example(example):
    cleaned = (example or "").strip()
    return cleaned or None


def get_word(conn, word_id):
    return conn.execute(
        "SELECT id, english, meaning, example, created_at FROM word WHERE id = ?",
        (word_id,),
    ).fetchone()


def list_words(conn):
    return conn.execute(
        "SELECT id, english, meaning, example, created_at FROM word ORDER BY id"
    ).fetchall()


def _find_duplicate(conn, english, excluded_id=None):
    row = conn.execute(
        "SELECT id FROM word WHERE english = ? AND id != ?",
        (english, excluded_id if excluded_id is not None else -1),
    ).fetchone()
    return row is not None


def add_word(conn, english, meaning, example=None):
    """단어를 등록하고 새 word_state 행을 함께 만든다 (FR-01.1)."""
    normalized = normalize_english(english)
    cleaned_meaning = _require_meaning(meaning)
    if _find_duplicate(conn, normalized):
        raise DuplicateWordError("이미 등록된 단어입니다.")
    created_at = datetime.now().isoformat(timespec="seconds")
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO word (english, meaning, example, created_at) VALUES (?, ?, ?, ?)",
                (normalized, cleaned_meaning, _optional_example(example), created_at),
            )
            word_id = cursor.lastrowid
            conn.execute("INSERT INTO word_state (word_id) VALUES (?)", (word_id,))
    except sqlite3.IntegrityError as error:
        raise DuplicateWordError("이미 등록된 단어입니다.") from error
    return word_id


def update_word(conn, word_id, english, meaning, example=None):
    """등록된 단어의 영어, 뜻, 예문을 바꾼다. 학습 상태는 유지한다 (FR-01.2)."""
    if get_word(conn, word_id) is None:
        raise WordError("단어를 찾을 수 없습니다.")
    normalized = normalize_english(english)
    cleaned_meaning = _require_meaning(meaning)
    if _find_duplicate(conn, normalized, excluded_id=word_id):
        raise DuplicateWordError("이미 등록된 단어입니다.")
    with conn:
        conn.execute(
            "UPDATE word SET english = ?, meaning = ?, example = ? WHERE id = ?",
            (normalized, cleaned_meaning, _optional_example(example), word_id),
        )


def delete_word(conn, word_id):
    """단어를 삭제한다. 학습 상태와 답안 기록도 CASCADE로 함께 삭제된다 (FR-01.3)."""
    with conn:
        cursor = conn.execute("DELETE FROM word WHERE id = ?", (word_id,))
    if cursor.rowcount == 0:
        raise WordError("단어를 찾을 수 없습니다.")
