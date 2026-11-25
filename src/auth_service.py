#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 회원 가입, 로그인 확인, 공개 여부 (도전 VOCA-FR-041·042·052)
# 파일 위치: src/auth_service.py
#
# 비밀번호는 해시(werkzeug)로만 저장한다. 평문은 DB에 들어가지 않는다 (VOCA-FR-042).

import re
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,20}$")
MIN_PASSWORD_LENGTH = 8


class AuthError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 계정 오류"""


def _normalize_username(username):
    return (username or "").strip().lower()


def create_user(conn, username, password, password_confirm):
    """회원을 만든다. 아이디는 소문자 영문·숫자·밑줄 3~20자."""
    name = _normalize_username(username)
    if not USERNAME_PATTERN.match(name):
        raise AuthError("아이디는 영문 소문자, 숫자, 밑줄(_)로 3~20자 입력하세요.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상 입력하세요.")
    if password != password_confirm:
        raise AuthError("비밀번호 확인이 일치하지 않습니다.")
    if conn.execute("SELECT 1 FROM app_user WHERE username = ?", (name,)).fetchone():
        raise AuthError("이미 사용 중인 아이디입니다.")
    created_at = datetime.now().isoformat(timespec="seconds")
    with conn:
        cursor = conn.execute(
            "INSERT INTO app_user (username, password_hash, is_public, created_at) VALUES (?, ?, 0, ?)",
            (name, generate_password_hash(password), created_at),
        )
    return cursor.lastrowid


def authenticate(conn, username, password):
    """아이디와 비밀번호가 맞으면 회원 번호를, 아니면 None을 돌려준다."""
    row = conn.execute(
        "SELECT id, password_hash FROM app_user WHERE username = ?",
        (_normalize_username(username),),
    ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None
    return row["id"]


def get_user(conn, user_id):
    return conn.execute(
        "SELECT id, username, is_public FROM app_user WHERE id = ?", (user_id,)
    ).fetchone()


def set_public(conn, user_id, is_public):
    """공개 여부를 정한다. 공개한 회원의 학습 기록만 다른 회원이 볼 수 있다 (VOCA-FR-052)."""
    with conn:
        conn.execute(
            "UPDATE app_user SET is_public = ? WHERE id = ?",
            (1 if is_public else 0, user_id),
        )


def public_users(conn):
    """공개 회원 목록 (VOCA-FR-051)."""
    return conn.execute(
        "SELECT id, username FROM app_user WHERE is_public = 1 ORDER BY username"
    ).fetchall()
