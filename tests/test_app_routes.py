#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-11-25 - 스마트보카 - 화면 라우트 통합 테스트 (임시 DB, Flask 테스트 클라이언트)
# 파일 위치: tests/test_app_routes.py
#
# Flask가 설치된 환경에서만 실행된다: python -m unittest discover -s tests

import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import exam_service  # noqa: E402
import study_service  # noqa: E402
import word_service  # noqa: E402

try:
    import app as voca_app  # noqa: E402
except ImportError:  # Flask가 없으면 이 파일은 건너뛴다
    voca_app = None

WORDS = [("apple", "사과"), ("banana", "바나나"), ("cherry", "체리"), ("grape", "포도"), ("lemon", "레몬")]
PASSWORD = "password123"


def signup_form(username):
    return {"username": username, "password": PASSWORD, "password_confirm": PASSWORD}


def settings_form(is_public, daily_target="20"):
    form = {
        "daily_target": daily_target,
        "review_ratio": "100",
        "exam_count": "10",
        "exam_direction": "mix",
        "exam_form": "mix",
    }
    if is_public:
        form["is_public"] = "on"
    return form


@unittest.skipIf(voca_app is None, "Flask가 설치되지 않았습니다")
class AppRoutesTest(unittest.TestCase):
    def setUp(self):
        study_service.reset_state()
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test.db")
        self.app = voca_app.create_app(self.db_path)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        seed = db.connect(self.db_path)
        for english, meaning in WORDS:
            word_service.add_word(seed, english, meaning)
        seed.close()
        self.client.post("/signup", data=signup_form("tester"))

    def tearDown(self):
        study_service.reset_state()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_pages_render(self):
        for path in ["/", "/words", "/words?q=app", "/cards", "/exam", "/report", "/study", "/settings", "/users"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_logged_out_pages_redirect_to_login(self):
        # 도전 VOCA-FR-041: 로그인하지 않으면 학습 화면을 열 수 없다
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/words").status_code, 302)
        self.assertIn("/login", anonymous.get("/words").headers["Location"])
        self.assertEqual(anonymous.post("/api/study/answer", json={}).status_code, 401)

    def test_login_and_logout_cycle(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post("/login", data={"username": "tester", "password": "wrong-pass"}).status_code, 302)
        self.assertEqual(anonymous.get("/words").status_code, 302)
        ok = anonymous.post("/login", data={"username": "tester", "password": "password123"})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(anonymous.get("/words").status_code, 200)
        anonymous.post("/logout")
        self.assertEqual(anonymous.get("/words").status_code, 302)

    def test_public_report_is_read_only_and_private_is_hidden(self):
        # 도전 VOCA-FR-051·052·053: 공개 회원의 기록은 보기만 되고, 비공개 회원의 기록은 숨긴다
        self.client.post("/settings", data=settings_form(is_public=True))
        friend = self.app.test_client()
        friend.post("/signup", data=signup_form("friend"))
        friend.post("/settings", data=settings_form(is_public=False))
        viewer = self.app.test_client()
        viewer.post("/signup", data=signup_form("viewer"))

        public_page = viewer.get("/users/1")
        self.assertEqual(public_page.status_code, 200)
        self.assertIn("tester 님의 학습 기록", public_page.get_data(as_text=True))
        self.assertIn("tester", viewer.get("/users").get_data(as_text=True))
        friend_id = db.connect(self.db_path).execute("SELECT id FROM app_user WHERE username = 'friend'").fetchone()[0]
        self.assertEqual(viewer.get(f"/users/{friend_id}").status_code, 404)

    def test_settings_roundtrip(self):
        # 도전 VOCA-FR-061·062: 저장한 설정이 다시 열어도 남아 있다
        self.client.post("/settings", data=settings_form(is_public=False, daily_target="12"))
        body = self.client.get("/settings").get_data(as_text=True)
        self.assertIn('value="12"', body)

    def test_settings_rejects_bad_daily_target(self):
        response = self.client.post("/settings", data=settings_form(is_public=False, daily_target="999"),
                                    follow_redirects=True)
        self.assertIn("하루 학습량은", response.get_data(as_text=True))

    def test_search_page_filters_words(self):
        response = self.client.get("/words?q=cherry")
        body = response.get_data(as_text=True)
        self.assertIn("cherry", body)
        self.assertNotIn("banana", body)

    def test_csv_upload_adds_words(self):
        data = {"csv_file": (io.BytesIO("english,meaning\nkiwi,키위\n".encode("utf-8")), "words.csv")}
        response = self.client.post("/words/import", data=data, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        check = db.connect(self.db_path)
        try:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM word").fetchone()[0], len(WORDS) + 1)
        finally:
            check.close()

    def test_exam_flow_from_start_to_result(self):
        # 시험을 만들고, 모든 문항에 정답을 넣고, 결과 화면이 모두 맞혔다고 말하는지 본다
        response = self.client.post("/exam", data={"count": "5", "direction": "en2ko", "form": "choice"})
        self.assertEqual(response.status_code, 302)
        exam_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
        check = db.connect(self.db_path)
        try:
            for _ in range(5):
                item = exam_service.current_item(check, exam_id)
                answer = self.client.post(
                    f"/exam/{exam_id}/answer",
                    data={"item_id": str(item["id"]), "answer": item["correct_answer"]},
                )
                self.assertEqual(answer.status_code, 302)
        finally:
            check.close()
        result = self.client.get(f"/exam/{exam_id}/result")
        self.assertEqual(result.status_code, 200)
        self.assertIn("모두 맞혔습니다.", result.get_data(as_text=True))

    def test_study_answer_api_grades_current_question(self):
        # 학습 화면의 답 제출(JSON)이 현재 문제를 채점하고 학습 기록을 남긴다
        self.assertEqual(self.client.get("/study").status_code, 200)
        active = study_service._active_sessions[1]
        question = active.current or study_service.current_question(db.connect(self.db_path), active)
        response = self.client.post(
            "/api/study/answer",
            json={"word_id": question["word_id"], "selected_meaning": question["correct_meaning"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["correct"])

    def test_unknown_exam_is_not_found(self):
        self.assertEqual(self.client.get("/exam/999/result").status_code, 404)


if __name__ == "__main__":
    unittest.main()
