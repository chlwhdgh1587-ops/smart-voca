#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - 세션 구성, 객관식 출제, 답안 처리, 복습 해제 (FR-02, FR-03)
# 파일 위치: src/study_service.py

import random
from dataclasses import dataclass, field
from datetime import datetime

DAILY_NEW_TARGET = 20      # FR-02: 하루 신규 단어 목표
MASTERY_STREAK = 3         # FR-02.4: 연속 정답 수 기준 (완벽 암기)
CHOICE_COUNT = 4           # FR-02.2: 보기 개수 (정답 1 + 오답 3)
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
    """서버 메모리에 두는 진행 중 세션 상태 (아키텍처 설계서 5절)"""

    session_id: int
    session_date: str
    blocks: list
    current: dict = None
    answered: int = 0
    correct: int = 0


_active = None
_last_finished_session_id = None


def reset_state():
    """메모리 상태를 비운다. 테스트와 앱 재시작 시 사용한다."""
    global _active, _last_finished_session_id
    _active = None
    _last_finished_session_id = None


def last_finished_session_id():
    return _last_finished_session_id


def _timestamp(today):
    """날짜 문자열에 현재 시각을 붙인다. 날짜 집계를 today와 맞추기 위해서다."""
    return f"{today}T{datetime.now().strftime('%H:%M:%S')}"


def _count_words(conn):
    return conn.execute("SELECT COUNT(*) FROM word").fetchone()[0]


def _count_distinct_meanings(conn):
    """보기 4개를 만들려면 서로 다른 뜻이 4개 이상 있어야 한다 (ADR-004)."""
    return conn.execute("SELECT COUNT(DISTINCT meaning) FROM word").fetchone()[0]


def _count_new_studied_today(conn, today):
    row = conn.execute(
        "SELECT COUNT(DISTINCT word_id) FROM attempt "
        "WHERE block = ? AND substr(attempted_at, 1, 10) = ?",
        (BLOCK_NEW, today),
    ).fetchone()
    return row[0]


def new_target_remaining(conn, today):
    """오늘 남은 신규 목표 수 (데이터 설계서 3절)"""
    return max(0, DAILY_NEW_TARGET - _count_new_studied_today(conn, today))


def _review_candidate_ids(conn, today):
    rows = conn.execute(
        "SELECT ws.word_id FROM word_state ws JOIN word w ON w.id = ws.word_id "
        "WHERE ws.in_review = 1 AND (ws.last_studied_on IS NULL OR ws.last_studied_on < ?) "
        "ORDER BY w.id",
        (today,),
    ).fetchall()
    return [row[0] for row in rows]


def _new_candidate_ids(conn, limit):
    rows = conn.execute(
        "SELECT ws.word_id FROM word_state ws JOIN word w ON w.id = ws.word_id "
        "WHERE ws.first_studied_on IS NULL ORDER BY w.id LIMIT ?",
        (limit,),
    ).fetchall()
    return [row[0] for row in rows]


def home_status(conn, today):
    """홈 화면에 표시할 오늘의 학습 현황"""
    new_available = conn.execute(
        "SELECT COUNT(*) FROM word_state WHERE first_studied_on IS NULL"
    ).fetchone()[0]
    return {
        "word_count": _count_words(conn),
        "can_study": _count_distinct_meanings(conn) >= CHOICE_COUNT,
        "review_count": len(_review_candidate_ids(conn, today)),
        "new_remaining": new_target_remaining(conn, today),
        "daily_target": DAILY_NEW_TARGET,
        "new_available": new_available,
    }


def _close_unfinished_sessions(conn, today):
    """재시작으로 끊긴 세션을 닫는다. 복습 대상은 건드리지 않는다 (프로세스 설계서 1절)."""
    with conn:
        conn.execute(
            "UPDATE study_session SET finished_at = ? WHERE finished_at IS NULL",
            (_timestamp(today),),
        )


def _build_blocks(conn, today):
    """복습 블록을 먼저, 신규 블록을 나중에 구성한다 (프로세스 설계서 1절)."""
    blocks = []
    review_ids = _review_candidate_ids(conn, today)
    if review_ids:
        blocks.append(
            Block(
                name=BLOCK_REVIEW,
                queue=list(review_ids),
                total=len(review_ids),
                review_target_ids=list(review_ids),
            )
        )
    remaining = new_target_remaining(conn, today)
    new_ids = _new_candidate_ids(conn, remaining) if remaining > 0 else []
    if new_ids:
        blocks.append(Block(name=BLOCK_NEW, queue=list(new_ids), total=len(new_ids)))
    return blocks, remaining


def resume_or_start_session(conn, today):
    """진행 중인 세션이 있으면 그대로 돌려주고, 없으면 새로 구성한다.

    학습할 것이 없으면 None을 돌려준다.
    """
    global _active
    if _active is not None and _active.session_date == today:
        return _active
    _active = None
    if _count_distinct_meanings(conn) < CHOICE_COUNT:
        raise StudyError("서로 다른 뜻의 단어를 4개 이상 등록해야 학습을 시작할 수 있습니다.")
    _close_unfinished_sessions(conn, today)
    blocks, remaining = _build_blocks(conn, today)
    if not blocks:
        return None
    with conn:
        cursor = conn.execute(
            "INSERT INTO study_session (session_date, started_at, new_target) VALUES (?, ?, ?)",
            (today, _timestamp(today), remaining),
        )
    _active = ActiveSession(session_id=cursor.lastrowid, session_date=today, blocks=blocks)
    return _active


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


def _finish_block(conn, block):
    """복습 블록이 끝나면 복습 대상을 해제한다 (FR-03.3)."""
    if block.name != BLOCK_REVIEW or not block.review_target_ids:
        return
    placeholders = ",".join("?" for _ in block.review_target_ids)
    with conn:
        conn.execute(
            f"UPDATE word_state SET in_review = 0 WHERE word_id IN ({placeholders})",
            block.review_target_ids,
        )


def _finish_session(conn, active, today):
    global _active, _last_finished_session_id
    with conn:
        conn.execute(
            "UPDATE study_session SET finished_at = ? WHERE id = ?",
            (_timestamp(today), active.session_id),
        )
    _active = None
    _last_finished_session_id = active.session_id


def _prepare_next(conn, active):
    """끝난 블록을 정리하고 다음 블록으로 넘어간다. 세션이 끝났으면 False를 돌려준다."""
    while active.blocks and not active.blocks[0].queue:
        _finish_block(conn, active.blocks.pop(0))
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
        "SELECT consecutive_correct FROM word_state WHERE word_id = ?", (word_id,)
    ).fetchone()
    new_streak = (previous[0] + 1) if is_correct else 0
    with conn:
        conn.execute(
            "INSERT INTO attempt (session_id, word_id, block, selected_meaning, is_correct, attempted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (active.session_id, word_id, block.name, selected_meaning, int(is_correct), _timestamp(today)),
        )
        conn.execute(
            "UPDATE word_state SET consecutive_correct = ?, last_studied_on = ?, in_review = 1 "
            "WHERE word_id = ?",
            (new_streak, today, word_id),
        )
        if block.name == BLOCK_NEW:
            conn.execute(
                "UPDATE word_state SET first_studied_on = ? WHERE word_id = ? AND first_studied_on IS NULL",
                (today, word_id),
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


def submit_answer(conn, word_id, selected_meaning, today):
    """학생의 답안을 처리하고 정답 여부를 돌려준다 (FR-02.3, FR-02.4)."""
    active = _active
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
    review_mastered = is_correct and in_review_block and new_streak >= MASTERY_STREAK
    session_finished = not _prepare_next(conn, active)
    return {
        "correct": is_correct,
        "correct_meaning": question["correct_meaning"],
        "example": question["example"],
        "review_continues": review_continues,
        "review_mastered": review_mastered,
        "session_finished": session_finished,
        "session_id": active.session_id,
    }
