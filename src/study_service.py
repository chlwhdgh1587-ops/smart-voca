#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 세션 구성, 객관식 출제, 답안 처리, 복습 해제 (FR-02, FR-03)
#   2026-11-25: 계정별 학습 상태, 설정 반영, 일차 계산, 자주 틀린 단어 섞기, 카드 목록 추가
# 파일 위치: src/study_service.py

import math
import random
from dataclasses import dataclass, field
from datetime import datetime

import settings_service

DAILY_NEW_TARGET = 20      # FR-02: 하루 신규 단어 목표 기본값 (계정 설정으로 바뀔 수 있음)
MASTERY_STREAK = 3         # FR-02.4: 연속 정답 수 기준 (완벽 암기)
CHOICE_COUNT = 4           # FR-02.2: 보기 개수 (정답 1 + 오답 3)
WEAK_WORD_MIN_WRONG = 2    # VOCA-FR-013: 이 횟수 이상 틀리면 '자주 틀린 단어'
WEAK_WORD_LIMIT = 5        # 한 세션의 복습 블록에 섞는 자주 틀린 단어 최대 수
BLOCK_REVIEW = "review"
BLOCK_NEW = "new"
BLOCK_LABELS = {BLOCK_REVIEW: "복습", BLOCK_NEW: "신규"}


class StudyError(Exception):
    """사용자에게 그대로 보여줄 수 있는 학습 진행 오류"""


@dataclass
class Block:
    """세션 안의 한 블록(복습 또는 신규). queue의 맨 앞이 현재 문제다."""

    name: str
    queue: list
    total: int
    review_target_ids: list = field(default_factory=list)

    def progress(self):
        """큐에서 빠져나간 단어 수. 재출제 때문에 total을 넘지 않는다."""
        return self.total - len(self.queue)


@dataclass
class ActiveSession:
    """서버 메모리에 두는 진행 중 세션 상태 (아키텍처 설계서 5절). 계정마다 하나씩 둔다."""

    user_id: int
    session_id: int
    session_date: str
    blocks: list
    current: dict = None
    answered: int = 0
    correct: int = 0


_active_sessions = {}      # user_id -> ActiveSession
_last_finished = {}        # user_id -> 마지막으로 끝난 session_id


def reset_state():
    """메모리 상태를 비운다. 테스트와 앱 재시작 시 사용한다."""
    _active_sessions.clear()
    _last_finished.clear()


def last_finished_session_id(user_id):
    return _last_finished.get(user_id)


def _timestamp(today):
    """날짜 문자열에 현재 시각을 붙인다. 날짜 집계를 today와 맞추기 위해서다."""
    return f"{today}T{datetime.now().strftime('%H:%M:%S')}"


def _count_words(conn):
    return conn.execute("SELECT COUNT(*) FROM word").fetchone()[0]


def _count_distinct_meanings(conn):
    """보기 4개를 만들려면 서로 다른 뜻이 4개 이상 있어야 한다 (ADR-004)."""
    return conn.execute("SELECT COUNT(DISTINCT meaning) FROM word").fetchone()[0]


def _count_new_studied_today(conn, user_id, today):
    row = conn.execute(
        "SELECT COUNT(DISTINCT word_id) FROM attempt "
        "WHERE user_id = ? AND block = ? AND substr(attempted_at, 1, 10) = ?",
        (user_id, BLOCK_NEW, today),
    ).fetchone()
    return row[0]


def new_target_remaining(conn, user_id, today, target):
    """오늘 남은 신규 목표 수 (데이터 설계서 3절)"""
    return max(0, target - _count_new_studied_today(conn, user_id, today))


def current_day_number(conn, user_id, today):
    """현재 일차. 신규 학습을 한 날짜를 1일차부터 센다 (VOCA-FR-011).

    오늘 아직 신규 학습을 하지 않았다면 오늘은 다음 일차다.
    """
    rows = conn.execute(
        "SELECT DISTINCT substr(attempted_at, 1, 10) FROM attempt WHERE user_id = ? AND block = ?",
        (user_id, BLOCK_NEW),
    ).fetchall()
    dates = {row[0] for row in rows}
    return len(dates) if today in dates else len(dates) + 1


def _review_candidate_ids(conn, user_id, today):
    """복습 대상: 복습 표시가 남은 단어 + 자주 틀린 단어 (VOCA-FR-013). 오늘 공부한 단어는 뺀다."""
    due = conn.execute(
        "SELECT ws.word_id FROM word_state ws JOIN word w ON w.id = ws.word_id "
        "WHERE ws.user_id = ? AND ws.in_review = 1 AND (ws.last_studied_on IS NULL OR ws.last_studied_on < ?)",
        (user_id, today),
    ).fetchall()
    ids = {row[0] for row in due}
    ids.update(_weak_word_ids(conn, user_id, today))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id FROM word WHERE id IN ({placeholders}) ORDER BY id", list(ids)
    ).fetchall()
    return [row[0] for row in rows]


def _weak_word_ids(conn, user_id, today):
    """자주 틀린 단어 ID. 틀린 횟수가 많은 순으로 고른다."""
    rows = conn.execute(
        "SELECT ws.word_id FROM word_state ws "
        "JOIN (SELECT word_id, COUNT(*) AS wrong FROM attempt "
        "      WHERE user_id = ? AND is_correct = 0 GROUP BY word_id) a ON a.word_id = ws.word_id "
        "WHERE ws.user_id = ? AND a.wrong >= ? AND ws.first_studied_on IS NOT NULL "
        "AND (ws.last_studied_on IS NULL OR ws.last_studied_on < ?) "
        "ORDER BY a.wrong DESC, ws.word_id LIMIT ?",
        (user_id, user_id, WEAK_WORD_MIN_WRONG, today, WEAK_WORD_LIMIT),
    ).fetchall()
    return [row[0] for row in rows]


def _apply_review_ratio(ids, ratio):
    """설정한 복습 비율(%)만큼만 오늘 낸다. 100이면 전부 낸다 (VOCA-FR-061)."""
    if ratio >= 100 or not ids:
        return ids
    keep = max(1, math.ceil(len(ids) * ratio / 100))
    return ids[:keep]


def _new_candidate_ids(conn, user_id, limit):
    rows = conn.execute(
        "SELECT w.id FROM word w LEFT JOIN word_state ws ON ws.word_id = w.id AND ws.user_id = ? "
        "WHERE ws.first_studied_on IS NULL ORDER BY w.id LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [row[0] for row in rows]


def home_status(conn, user_id, today):
    """홈 화면에 표시할 오늘의 학습 현황"""
    settings = settings_service.get_settings(conn, user_id)
    target = settings["daily_target"]
    new_available = conn.execute(
        "SELECT COUNT(*) FROM word w LEFT JOIN word_state ws ON ws.word_id = w.id AND ws.user_id = ? "
        "WHERE ws.first_studied_on IS NULL",
        (user_id,),
    ).fetchone()[0]
    return {
        "word_count": _count_words(conn),
        "can_study": _count_distinct_meanings(conn) >= CHOICE_COUNT,
        "review_count": len(_review_candidate_ids(conn, user_id, today)),
        "new_remaining": new_target_remaining(conn, user_id, today, target),
        "daily_target": target,
        "new_available": new_available,
        "day_number": current_day_number(conn, user_id, today),
    }


def todays_new_words(conn, user_id, today):
    """카드 암기용 오늘의 신규 단어 목록.

    오늘 이미 처음 공부한 단어를 먼저 두고, 목표 수에 모자라는 만큼 다음 신규 단어를 채운다.
    카드 화면은 읽기 전용이라 학습 기록을 남기지 않는다 (VOCA-FR-012).
    """
    target = settings_service.get_settings(conn, user_id)["daily_target"]
    studied = conn.execute(
        "SELECT w.id, w.english, w.meaning, w.example FROM word_state ws JOIN word w ON w.id = ws.word_id "
        "WHERE ws.user_id = ? AND ws.first_studied_on = ? ORDER BY w.id",
        (user_id, today),
    ).fetchall()
    extra_ids = _new_candidate_ids(conn, user_id, max(0, target - len(studied)))
    words = [dict(row) for row in studied]
    for word_id in extra_ids:
        row = conn.execute(
            "SELECT id, english, meaning, example FROM word WHERE id = ?", (word_id,)
        ).fetchone()
        words.append(dict(row))
    return words


def _close_unfinished_sessions(conn, user_id, today):
    """재시작으로 끊긴 세션을 닫는다. 복습 대상은 건드리지 않는다 (프로세스 설계서 1절)."""
    with conn:
        conn.execute(
            "UPDATE study_session SET finished_at = ? WHERE user_id = ? AND finished_at IS NULL",
            (_timestamp(today), user_id),
        )


def _build_blocks(conn, user_id, today, settings):
    """복습 블록을 먼저, 신규 블록을 나중에 구성한다 (프로세스 설계서 1절)."""
    blocks = []
    review_ids = _apply_review_ratio(
        _review_candidate_ids(conn, user_id, today), settings["review_ratio"]
    )
    if review_ids:
        blocks.append(
            Block(
                name=BLOCK_REVIEW,
                queue=list(review_ids),
                total=len(review_ids),
                review_target_ids=list(review_ids),
            )
        )
    remaining = new_target_remaining(conn, user_id, today, settings["daily_target"])
    new_ids = _new_candidate_ids(conn, user_id, remaining) if remaining > 0 else []
    if new_ids:
        blocks.append(Block(name=BLOCK_NEW, queue=list(new_ids), total=len(new_ids)))
    return blocks, remaining


def resume_or_start_session(conn, user_id, today):
    """진행 중인 세션이 있으면 그대로 돌려주고, 없으면 새로 구성한다.

    학습할 것이 없으면 None을 돌려준다.
    """
    active = _active_sessions.get(user_id)
    if active is not None and active.session_date == today:
        return active
    _active_sessions.pop(user_id, None)
    if _count_distinct_meanings(conn) < CHOICE_COUNT:
        raise StudyError("서로 다른 뜻의 단어를 4개 이상 등록해야 학습을 시작할 수 있습니다.")
    _close_unfinished_sessions(conn, user_id, today)
    settings = settings_service.get_settings(conn, user_id)
    blocks, remaining = _build_blocks(conn, user_id, today, settings)
    if not blocks:
        return None
    with conn:
        cursor = conn.execute(
            "INSERT INTO study_session (user_id, session_date, started_at, new_target) VALUES (?, ?, ?, ?)",
            (user_id, today, _timestamp(today), remaining),
        )
    active = ActiveSession(user_id=user_id, session_id=cursor.lastrowid, session_date=today, blocks=blocks)
    _active_sessions[user_id] = active
    return active


def _pick_distractors(conn, word_id, meaning, rng):
    """정답과 다른 뜻 중에서 오답 3개를 고른다 (FR-02.2, ADR-004)."""
    rows = conn.execute(
        "SELECT DISTINCT meaning FROM word WHERE id != ? AND meaning != ? ORDER BY meaning",
        (word_id, meaning),
    ).fetchall()
    candidates = [row[0] for row in rows]
    if len(candidates) < CHOICE_COUNT - 1:
        raise StudyError("보기를 만들 뜻이 부족합니다. 서로 다른 뜻의 단어를 4개 이상 등록하세요.")
    return rng.sample(candidates, CHOICE_COUNT - 1)


def _make_question(conn, block, rng):
    """블록 큐 맨 앞 단어로 문제를 만든다. 단어가 사라졌으면 큐에서 빼고 None을 돌려준다."""
    word_id = block.queue[0]
    row = conn.execute(
        "SELECT id, english, meaning, example FROM word WHERE id = ?", (word_id,)
    ).fetchone()
    if row is None:
        block.queue.pop(0)
        return None
    options = _pick_distractors(conn, word_id, row["meaning"], rng) + [row["meaning"]]
    rng.shuffle(options)
    return {
        "word_id": word_id,
        "english": row["english"],
        "example": row["example"],
        "correct_meaning": row["meaning"],
        "options": options,
        "block": block.name,
        "block_label": BLOCK_LABELS[block.name],
        "block_done": block.progress(),
        "block_total": block.total,
    }


def _finish_block(conn, user_id, block):
    """복습 블록이 끝나면 복습 대상을 해제한다 (FR-03.3)."""
    if block.name != BLOCK_REVIEW or not block.review_target_ids:
        return
    placeholders = ",".join("?" for _ in block.review_target_ids)
    with conn:
        conn.execute(
            f"UPDATE word_state SET in_review = 0 WHERE user_id = ? AND word_id IN ({placeholders})",
            [user_id, *block.review_target_ids],
        )


def _finish_session(conn, active, today):
    with conn:
        conn.execute(
            "UPDATE study_session SET finished_at = ? WHERE id = ?",
            (_timestamp(today), active.session_id),
        )
    _active_sessions.pop(active.user_id, None)
    _last_finished[active.user_id] = active.session_id


def _prepare_next(conn, active):
    """끝난 블록을 정리하고 다음 블록으로 넘어간다. 세션이 끝났으면 False를 돌려준다."""
    while active.blocks and not active.blocks[0].queue:
        _finish_block(conn, active.user_id, active.blocks.pop(0))
    if active.blocks:
        return True
    _finish_session(conn, active, active.session_date)
    return False


def current_question(conn, active, rng=None):
    """현재 문제를 돌려준다. 세션이 끝났으면 None을 돌려준다."""
    rng = rng or random
    while active.current is None:
        if not _prepare_next(conn, active):
            return None
        active.current = _make_question(conn, active.blocks[0], rng)
    return active.current


def _record_attempt(conn, active, block, word_id, selected_meaning, is_correct, today):
    """답안을 저장하고 연속 정답 수를 갱신한다. 갱신된 연속 정답 수를 돌려준다."""
    previous = conn.execute(
        "SELECT consecutive_correct FROM word_state WHERE user_id = ? AND word_id = ?",
        (active.user_id, word_id),
    ).fetchone()
    if is_correct:
        new_streak = (previous[0] if previous else 0) + 1
    else:
        new_streak = 0
    first_studied = today if block.name == BLOCK_NEW else None
    with conn:
        conn.execute(
            "INSERT INTO attempt (session_id, user_id, word_id, block, selected_meaning, is_correct, attempted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                active.session_id,
                active.user_id,
                word_id,
                block.name,
                selected_meaning,
                int(is_correct),
                _timestamp(today),
            ),
        )
        conn.execute(
            "INSERT INTO word_state (user_id, word_id, consecutive_correct, first_studied_on, last_studied_on, in_review) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(user_id, word_id) DO UPDATE SET "
            "consecutive_correct = excluded.consecutive_correct, "
            "last_studied_on = excluded.last_studied_on, "
            "first_studied_on = COALESCE(word_state.first_studied_on, excluded.first_studied_on), "
            "in_review = 1",
            (active.user_id, word_id, new_streak, first_studied, today),
        )
    return new_streak


def _needs_repeat(block, is_correct, new_streak):
    """문제를 큐 끝에 다시 넣어야 하는지 판정한다 (프로세스 설계서 3절).

    - 틀리면 항상 다시 낸다 (FR-02.3).
    - 복습 블록에서는 맞혀도 연속 3회에 도달할 때까지 다시 낸다 (FR-03.2).
    """
    if not is_correct:
        return True
    return block.name == BLOCK_REVIEW and new_streak < MASTERY_STREAK


def submit_answer(conn, user_id, word_id, selected_meaning, today):
    """학생의 답안을 처리하고 정답 여부를 돌려준다 (FR-02.3, FR-02.4)."""
    active = _active_sessions.get(user_id)
    if active is None or active.current is None:
        raise StudyError("진행 중인 문제가 없습니다.")
    if active.current["word_id"] != word_id:
        raise StudyError("현재 문제와 일치하지 않습니다.")
    question = active.current
    block = active.blocks[0]
    is_correct = selected_meaning == question["correct_meaning"]
    new_streak = _record_attempt(conn, active, block, word_id, selected_meaning, is_correct, today)
    block.queue.pop(0)
    if _needs_repeat(block, is_correct, new_streak):
        block.queue.append(word_id)
    active.current = None
    active.answered += 1
    active.correct += int(is_correct)
    in_review_block = block.name == BLOCK_REVIEW
    review_continues = is_correct and in_review_block and new_streak < MASTERY_STREAK
    review_block_done = in_review_block and not block.queue
    session_finished = not _prepare_next(conn, active)
    return {
        "correct": is_correct,
        "correct_meaning": question["correct_meaning"],
        "example": question["example"],
        "review_continues": review_continues,
        "review_block_done": review_block_done,
        "session_finished": session_finished,
        "session_id": active.session_id,
    }
