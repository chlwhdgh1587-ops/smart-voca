#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - Flask 진입점과 HTTP 라우트 (아키텍처 설계서 5절)
#   2026-11-25: 검색·CSV 가져오기, 카드 암기, 시험, 통계 확장 라우트 추가
# 파일 위치: src/app.py
#
# 실행: python src/app.py  →  http://127.0.0.1:5000
# 서버: gunicorn --chdir src --bind 0.0.0.0:8080 "app:create_app()"

import os
import secrets
from datetime import date

from flask import (
    Flask, abort, flash, g, current_app, jsonify, redirect, render_template, request, session, url_for,
)

import auth_service
import db
import exam_service
import report_service
import settings_service
import study_service
import word_service

MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # 서버 요건: 업로드 20MB 이하
PUBLIC_ENDPOINTS = {"login_page", "signup_page", "static"}   # 로그인 없이 열 수 있는 화면


def get_db():
    """요청마다 하나의 DB 연결을 쓴다."""
    if "conn" not in g:
        g.conn = db.connect(current_app.config["DB_PATH"])
    return g.conn


def current_user_id():
    """로그인한 회원 번호. 로그인 게이트를 통과한 요청에서만 불린다."""
    return session["user_id"]


def today_string():
    return date.today().isoformat()


def create_app(db_path=None):
    app = Flask(__name__)
    # 세션 키는 환경변수 SECRET_KEY로 받는다. 없으면 기동할 때 무작위로 만든다 (코드·이미지에 비밀값을 두지 않는다).
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    # DB 위치: 인자 > 환경변수 DB_PATH > 기본값 data/smartvoca.db. 서버에서는 DB_PATH=/data/voca.db.
    app.config["DB_PATH"] = db_path or os.environ.get("DB_PATH")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    # 세션 쿠키는 다른 사이트에서 보낸 POST에 붙지 않게 한다 (CSRF 완화)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    @app.teardown_appcontext
    def close_db(_error):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def require_login():
        """로그인하지 않은 요청은 로그인 화면으로 보낸다. API는 401을 돌려준다."""
        if request.endpoint in PUBLIC_ENDPOINTS or "user_id" in session:
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "로그인이 필요합니다."}), 401
        flash("로그인이 필요합니다.", "error")
        return redirect(url_for("login_page"))

    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        if request.method == "POST":
            user_id = auth_service.authenticate(
                get_db(), request.form.get("username", ""), request.form.get("password", "")
            )
            if user_id is None:
                flash("아이디 또는 비밀번호가 맞지 않습니다.", "error")
                return redirect(url_for("login_page"))
            session.clear()
            session["user_id"] = user_id
            session["username"] = auth_service.get_user(get_db(), user_id)["username"]
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.route("/signup", methods=["GET", "POST"])
    def signup_page():
        if request.method == "POST":
            try:
                user_id = auth_service.create_user(
                    get_db(),
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                    request.form.get("password_confirm", ""),
                )
            except auth_service.AuthError as error:
                flash(str(error), "error")
                return redirect(url_for("signup_page"))
            session.clear()
            session["user_id"] = user_id
            session["username"] = auth_service.get_user(get_db(), user_id)["username"]
            flash("가입했습니다. 환영합니다!")
            return redirect(url_for("home"))
        return render_template("signup.html")

    @app.route("/logout", methods=["POST"])
    def logout_page():
        session.clear()
        flash("로그아웃했습니다.")
        return redirect(url_for("login_page"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        conn = get_db()
        user_id = current_user_id()
        if request.method == "POST":
            try:
                settings_service.save_settings(conn, user_id, request.form)
                auth_service.set_public(conn, user_id, request.form.get("is_public") == "on")
                flash("설정을 저장했습니다.")
                return redirect(url_for("settings_page"))
            except settings_service.SettingError as error:
                flash(str(error), "error")
                return redirect(url_for("settings_page"))
        user = auth_service.get_user(conn, user_id)
        return render_template(
            "settings.html",
            values=settings_service.get_settings(conn, user_id),
            is_public=bool(user["is_public"]),
            daily_range=settings_service.DAILY_TARGET_RANGE,
            review_ratios=settings_service.REVIEW_RATIOS,
            exam_counts=settings_service.EXAM_COUNTS,
        )

    @app.route("/users")
    def users_page():
        conn = get_db()
        today = today_string()
        rows = []
        for user in auth_service.public_users(conn):
            progress = report_service.progress_summary(conn, user["id"], today)
            rows.append({"id": user["id"], "username": user["username"], "progress": progress})
        return render_template("users.html", rows=rows, me=current_user_id())

    @app.route("/users/<int:user_id>")
    def user_report_page(user_id):
        conn = get_db()
        if user_id == current_user_id():
            return redirect(url_for("report_page"))
        user = auth_service.get_user(conn, user_id)
        if user is None or not user["is_public"]:
            abort(404)
        today = today_string()
        return render_template(
            "report.html",
            owner=user["username"],
            daily=report_service.daily_summary(conn, user_id),
            mastery=report_service.mastery_summary(conn, user_id),
            progress=report_service.progress_summary(conn, user_id, today),
            trend=report_service.exam_trend(conn, user_id),
            weak=report_service.weak_words(conn, user_id),
        )

    @app.route("/")
    def home():
        status = study_service.home_status(get_db(), current_user_id(), today_string())
        return render_template("home.html", status=status)

    @app.route("/study")
    def study():
        conn = get_db()
        user_id = current_user_id()
        try:
            active = study_service.resume_or_start_session(conn, user_id, today_string())
            question = study_service.current_question(conn, active) if active else None
        except study_service.StudyError as error:
            flash(str(error), "error")
            return redirect(url_for("home"))
        if question is None:
            if active is None:
                flash("오늘 할 학습이 없습니다.")
                return redirect(url_for("home"))
            return redirect(url_for("study_done"))
        return render_template("study.html", question=question)

    @app.route("/api/study/answer", methods=["POST"])
    def answer_api():
        payload = request.get_json(silent=True) or {}
        try:
            result = study_service.submit_answer(
                get_db(),
                current_user_id(),
                int(payload.get("word_id")),
                str(payload.get("selected_meaning", "")),
                today_string(),
            )
        except (study_service.StudyError, TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(result)

    @app.route("/study/done")
    def study_done():
        user_id = current_user_id()
        session_id = study_service.last_finished_session_id(user_id)
        if session_id is None:
            return redirect(url_for("home"))
        conn = get_db()
        return render_template(
            "done.html",
            summary=report_service.session_summary(conn, user_id, session_id),
            mastery=report_service.mastery_summary(conn, user_id),
        )

    @app.route("/cards")
    def cards_page():
        words = study_service.todays_new_words(get_db(), current_user_id(), today_string())
        return render_template("cards.html", words=words)

    @app.route("/words")
    def words_page():
        query = request.args.get("q", "").strip()
        words = word_service.list_words(get_db(), query)
        return render_template("words.html", words=words, query=query)

    @app.route("/words", methods=["POST"])
    def add_word_page():
        try:
            word_service.add_word(
                get_db(),
                request.form.get("english", ""),
                request.form.get("meaning", ""),
                request.form.get("example"),
            )
            flash("단어를 등록했습니다.")
        except word_service.WordError as error:
            flash(str(error), "error")
        return redirect(url_for("words_page"))

    @app.route("/words/import", methods=["POST"])
    def import_words_page():
        uploaded = request.files.get("csv_file")
        if uploaded is None or not uploaded.filename:
            flash("가져올 CSV 파일을 고르세요.", "error")
            return redirect(url_for("words_page"))
        try:
            result = word_service.import_words_csv(get_db(), uploaded.read())
            flash(
                f"가져오기 완료: 추가 {result['added']}개, 중복 건너뜀 {result['duplicate']}개, "
                f"잘못된 행 {result['invalid']}개"
            )
        except word_service.WordError as error:
            flash(str(error), "error")
        return redirect(url_for("words_page"))

    @app.route("/words/<int:word_id>/edit", methods=["POST"])
    def edit_word_page(word_id):
        try:
            word_service.update_word(
                get_db(),
                word_id,
                request.form.get("english", ""),
                request.form.get("meaning", ""),
                request.form.get("example"),
            )
            flash("단어를 수정했습니다.")
        except word_service.WordError as error:
            flash(str(error), "error")
        return redirect(url_for("words_page"))

    @app.route("/words/<int:word_id>/delete", methods=["POST"])
    def delete_word_page(word_id):
        try:
            word_service.delete_word(get_db(), word_id)
            flash("단어를 삭제했습니다.")
        except word_service.WordError as error:
            flash(str(error), "error")
        return redirect(url_for("words_page"))

    @app.route("/exam")
    def exam_page():
        conn = get_db()
        user_id = current_user_id()
        return render_template(
            "exam_setup.html",
            defaults=settings_service.get_settings(conn, user_id),
            unfinished_id=exam_service.unfinished_exam_id(conn, user_id),
            count_options=settings_service.EXAM_COUNTS,
        )

    @app.route("/exam", methods=["POST"])
    def exam_start():
        try:
            count = int(request.form.get("count", ""))
        except ValueError:
            flash("문제 수를 고르세요.", "error")
            return redirect(url_for("exam_page"))
        try:
            exam_id = exam_service.create_exam(
                get_db(),
                current_user_id(),
                count,
                request.form.get("direction", ""),
                request.form.get("form", ""),
                today_string(),
            )
        except exam_service.ExamError as error:
            flash(str(error), "error")
            return redirect(url_for("exam_page"))
        return redirect(url_for("exam_play", exam_id=exam_id))

    @app.route("/exam/<int:exam_id>")
    def exam_play(exam_id):
        conn = get_db()
        try:
            exam = exam_service.get_exam(conn, current_user_id(), exam_id)
        except exam_service.ExamError as error:
            flash(str(error), "error")
            return redirect(url_for("exam_page"))
        if exam["finished_at"] is not None:
            return redirect(url_for("exam_result", exam_id=exam_id))
        item = exam_service.current_item(conn, exam_id)
        if item is None:
            return redirect(url_for("exam_result", exam_id=exam_id))
        return render_template("exam_item.html", item=item, exam_id=exam_id)

    @app.route("/exam/<int:exam_id>/answer", methods=["POST"])
    def exam_answer(exam_id):
        try:
            item_id = int(request.form.get("item_id", ""))
            result = exam_service.answer_item(
                get_db(),
                current_user_id(),
                exam_id,
                item_id,
                request.form.get("answer", ""),
                today_string(),
            )
        except (exam_service.ExamError, ValueError) as error:
            flash(str(error), "error")
            return redirect(url_for("exam_play", exam_id=exam_id))
        if result["is_correct"]:
            flash("정답입니다.")
        else:
            flash(f"틀렸습니다. 정답은 {result['correct_answer']} 입니다.", "error")
        if result["finished"]:
            return redirect(url_for("exam_result", exam_id=exam_id))
        return redirect(url_for("exam_play", exam_id=exam_id))

    @app.route("/exam/<int:exam_id>/result")
    def exam_result(exam_id):
        try:
            result = exam_service.exam_result(get_db(), current_user_id(), exam_id)
        except exam_service.ExamError:
            abort(404)
        if not result["finished"]:
            return redirect(url_for("exam_play", exam_id=exam_id))
        return render_template("exam_result.html", result=result)

    @app.route("/report")
    def report_page():
        conn = get_db()
        user_id = current_user_id()
        return render_template(
            "report.html",
            daily=report_service.daily_summary(conn, user_id),
            mastery=report_service.mastery_summary(conn, user_id),
            progress=report_service.progress_summary(conn, user_id, today_string()),
            trend=report_service.exam_trend(conn, user_id),
            weak=report_service.weak_words(conn, user_id),
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False, threaded=False)
