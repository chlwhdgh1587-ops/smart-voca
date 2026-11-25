#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 회원 가입과 로그인 확인 단위 테스트 (도전 VOCA-FR-041·042)
# 파일 위치: tests/test_auth_service.py

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import auth_service  # noqa: E402
import db  # noqa: E402


class AuthServiceTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(db.MEMORY_DB)

    def tearDown(self):
        self.conn.close()

    def test_password_is_stored_as_hash(self):
        # VOCA-FR-042: 평문 비밀번호는 DB에 들어가지 않는다
        auth_service.create_user(self.conn, "Teacher_1", "password123", "password123")
        stored = self.conn.execute("SELECT username, password_hash FROM app_user").fetchone()
        self.assertEqual(stored["username"], "teacher_1")
        self.assertNotIn("password123", stored["password_hash"])

    def test_authenticate_accepts_right_password_only(self):
        user_id = auth_service.create_user(self.conn, "student", "password123", "password123")
        self.assertEqual(auth_service.authenticate(self.conn, "STUDENT", "password123"), user_id)
        self.assertIsNone(auth_service.authenticate(self.conn, "student", "password124"))
        self.assertIsNone(auth_service.authenticate(self.conn, "nobody", "password123"))

    def test_invalid_signup_inputs_are_rejected(self):
        cases = [
            ("ab", "password123", "password123"),        # 아이디가 짧음
            ("bad name", "password123", "password123"),  # 공백
            ("student", "short", "short"),               # 비밀번호가 짧음
            ("student", "password123", "password124"),   # 확인 불일치
        ]
        for username, password, confirm in cases:
            with self.subTest(username=username, password=password, confirm=confirm):
                with self.assertRaises(auth_service.AuthError):
                    auth_service.create_user(self.conn, username, password, confirm)

    def test_duplicate_username_is_rejected(self):
        auth_service.create_user(self.conn, "student", "password123", "password123")
        with self.assertRaises(auth_service.AuthError):
            auth_service.create_user(self.conn, "Student", "password123", "password123")

    def test_public_flag_controls_public_list(self):
        user_id = auth_service.create_user(self.conn, "student", "password123", "password123")
        self.assertEqual(auth_service.public_users(self.conn), [])
        auth_service.set_public(self.conn, user_id, True)
        self.assertEqual([row["username"] for row in auth_service.public_users(self.conn)], ["student"])


if __name__ == "__main__":
    unittest.main()
