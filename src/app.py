#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 2026-10-21 - 스마트보카 - Flask 진입점과 HTTP 라우트 (아키텍처 설계서 5절)
# 파일 위치: src/app.py
#
# 실행: python src/app.py  →  http://127.0.0.1:5000

import os
from datetime import date

from flask import Flask, flash, g, current_app, jsonify, redirect, render_template, request, url_for

import db
import report_service
import study_service
import word_service


def get_db():
    """요청마다 하나의 DB 연결을 쓴다."""
    if "conn" not in g:
        g.conn = db.connect(current_app.config["DB_PATH"])
    return g.conn


def today_string():
    return date.today().isoformat()


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SMARTVOCA_SECRET_KEY", "smartvoca-local-only")
    app.config["DB_PATH"] = db_path

    @app.teardown_appcontext
    def close_db(_error):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.route("/")
    def home():
        status = study_service.home_status(get_db(), today_string())
        return render_template("home.html", status=status)

    @app.route("/study")
    def study():
        conn = get_db()
        try:
            active = study_service.resume_or_start_session(conn, today_string())
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
                int(payload.get("word_id")),
                str(payload.get("selected_meaning", "")),
                today_string(),
            )
        except (study_service.StudyError, TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(result)

    @app.route("/study/done")
    def study_done():
        session_id = study_service.last_finished_session_id()
        if session_id is None:
            return redirect(url_for("home"))
        conn = get_db()
        return render_template(
            "done.html",
            summary=report_service.session_summary(conn, session_id),
            mastery=report_service.mastery_summary(conn),
        )

    @app.route("/words")
    def words_page():
        return render_template("words.html", words=word_service.list_words(get_db()))

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

    @app.route("/report")
    def report_page():
        conn = get_db()
        return render_template(
            "report.html",
            daily=report_service.daily_summary(conn),
            mastery=report_service.mastery_summary(conn),
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False, threaded=False)
