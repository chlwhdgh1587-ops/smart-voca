# 2026-11-25 - 스마트보카 - 학교 서버 배포용 이미지 (Dockerfile 구성 R-01~R-16)
# 파일 위치: Dockerfile
# 빌드: docker build .   실행 예: docker run -p 8080:8080 -v voca-data:/data smartvoca

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/voca.db

WORKDIR /app

# 의존성 파일을 소스보다 먼저 복사한다. 소스만 바뀐 빌드에서 pip 설치 단계를 캐시로 건너뛴다 (R-13)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# UID 10001 전용 사용자를 만들고 쓰기 가능한 /data를 준비한다 (R-05, R-06)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown 10001:10001 /data

COPY src/ ./src/

USER 10001

EXPOSE 8080

# gunicorn 워커는 1개로 둔다. 세션 키가 프로세스마다 무작위라 워커가 여럿이면 로그인 세션이 깨진다.
CMD ["gunicorn", "--chdir", "src", "--bind", "0.0.0.0:8080", "app:create_app()"]
