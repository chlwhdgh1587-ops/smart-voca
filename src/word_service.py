#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 단어 등록, 수정, 삭제, 검색, CSV 가져오기 (FR-01, 2026-11-25 VOCA-FR-003·004)
# 파일 위치: src/word_service.py

import csv
import io
import sqlite3
from datetime import datetime

# CSV 머리글 허용 이름 (영문 또는 한글). 공지의 "영단어,뜻" 형식과 기존 words_public.csv 둘 다 받는다.
ENGLISH_HEADERS = {"english", "영단어", "영어"}
MEANING_HEADERS = {"meaning", "뜻"}
EXAMPLE_HEADERS = {"example", "예문"}


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


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_word(conn, word_id):
    return conn.execute(
        "SELECT id, english, meaning, example, created_at FROM word WHERE id = ?",
        (word_id,),
    ).fetchone()


def list_words(conn, query=None):
    """단어 목록. query가 있으면 영단어 또는 뜻에 포함된 단어만 돌려준다 (VOCA-FR-004)."""
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return conn.execute(
            "SELECT id, english, meaning, example, created_at FROM word ORDER BY id"
        ).fetchall()
    pattern = f"%{_escape_like(cleaned_query.lower())}%"
    return conn.execute(
        "SELECT id, english, meaning, example, created_at FROM word "
        "WHERE lower(english) LIKE ? ESCAPE '\\' OR lower(meaning) LIKE ? ESCAPE '\\' ORDER BY id",
        (pattern, pattern),
    ).fetchall()


def _find_duplicate(conn, english, excluded_id=None):
    row = conn.execute(
        "SELECT id FROM word WHERE english = ? AND id != ?",
        (english, excluded_id if excluded_id is not None else -1),
    ).fetchone()
    return row is not None


def add_word(conn, english, meaning, example=None):
    """단어를 등록한다. 학습 상태(word_state)는 그 계정이 처음 공부할 때 만든다 (FR-01.1)."""
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
    except sqlite3.IntegrityError as error:
        raise DuplicateWordError("이미 등록된 단어입니다.") from error
    return cursor.lastrowid


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


def _map_headers(fieldnames):
    """머리글 이름을 영어·뜻·예문 열로 찾는다. 영어와 뜻 열이 없으면 오류."""
    lowered = {(name or "").strip().lower(): name for name in fieldnames or []}
    english_key = next((lowered[h] for h in ENGLISH_HEADERS if h in lowered), None)
    meaning_key = next((lowered[h] for h in MEANING_HEADERS if h in lowered), None)
    example_key = next((lowered[h] for h in EXAMPLE_HEADERS if h in lowered), None)
    if english_key is None or meaning_key is None:
        raise WordError("CSV 첫 줄에 영단어(english)와 뜻(meaning) 열이 있어야 합니다.")
    return english_key, meaning_key, example_key


def import_words_csv(conn, raw_bytes):
    """CSV 바이트를 읽어 단어를 일괄 등록한다 (VOCA-FR-003).

    중복 방침: 영어 단어가 이미 있으면 건너뛴다(기존 뜻과 예문을 덮어쓰지 않는다).
    잘못된 행(영어 또는 뜻이 비어 있음)도 건너뛰고 건수만 센다.
    파일은 디스크에 쓰지 않고 메모리에서만 처리한다 (VOCA-SUB-035).
    """
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise WordError("UTF-8 형식의 CSV 파일만 가져올 수 있습니다.") from error
    reader = csv.DictReader(io.StringIO(text))
    english_key, meaning_key, example_key = _map_headers(reader.fieldnames)
    result = {"added": 0, "duplicate": 0, "invalid": 0}
    for row in reader:
        english = row.get(english_key) or ""
        meaning = row.get(meaning_key) or ""
        example = row.get(example_key) if example_key else None
        try:
            add_word(conn, english, meaning, example)
            result["added"] += 1
        except DuplicateWordError:
            result["duplicate"] += 1
        except WordError:
            result["invalid"] += 1
    return result
