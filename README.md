# 스마트보카 (Smart Voca)

영단어를 4지선다로 외우는 개인용 객관식 단어 암기 웹 앱입니다. 하루 신규 단어 20개를 배우고, 연속 3회 정답이면 완벽 암기로 봅니다. 틀린 단어는 같은 세션에서 맞힐 때까지 다시 나오고, 다음 날 복습 블록에서 다시 확인합니다.

- 작성자: 260134 최종호
- 기말 과제(AI기반 프로그래밍) 산출물
- 설계 문서: `docs/` (기획, 분석, 설계, 테스트, 운영)
- 작업 방식과 요구사항 ID 추적: `CLAUDE.md`

## 고른 DB

**SQLite** (표준 라이브러리 `sqlite3`). 파일 위치는 환경변수 `DB_PATH`로 정하고, 없으면 `data/smartvoca.db`를 씁니다. 처음 실행할 때 테이블을 자동으로 만듭니다.

## 실행 방법

### 1. 교실 PC에서 직접 실행 (Python 3.11)

```bash
python -m pip install -r requirements.txt
python src/seed_words.py      # 기초 단어 적재 (최초 1회, 선택)
python src/app.py             # http://127.0.0.1:5000 접속
```

### 2. Docker 이미지로 실행 (서버와 같은 조건)

```bash
docker build -t smartvoca .
docker run --rm -p 8080:8080 -e SECRET_KEY=change-me -v smartvoca-data:/data smartvoca
```

접속: `http://127.0.0.1:8080`

- `SECRET_KEY`를 주지 않으면 기동할 때 무작위 값을 만듭니다.
- 데이터는 컨테이너의 `/data/voca.db`에 저장됩니다. 볼륨을 붙이면 재시작 후에도 남습니다.
- 컨테이너는 UID 10001로 실행되며 root 권한을 쓰지 않습니다.

## 환경변수

| 이름 | 기본값 | 설명 |
|------|--------|------|
| `SECRET_KEY` | 무작위 생성 | 세션 서명 키 |
| `DB_PATH` | `data/smartvoca.db` (Docker: `/data/voca.db`) | SQLite 파일 위치 |

## 구현한 요구사항 ID

요구사항 ID는 과제 공지의 VOCA-FR 목록을 따릅니다. 1차 제출 시점의 구현 상태입니다.

| ID | 요구사항 | 상태 |
|----|----------|------|
| VOCA-FR-001 | 영단어와 뜻을 직접 입력해 등록 | 구현 |
| VOCA-FR-002 | 단어 목록 보기, 수정·삭제 | 구현 |
| VOCA-FR-003 | CSV 일괄 등록 | 부분 (명령행 `src/seed_words.py`만. 웹 업로드와 중복 처리 방침 문서화 필요) |
| VOCA-FR-004 | 단어 검색 | 미구현 |
| VOCA-FR-011 | 하루 학습량에 따른 진도 | 부분 (하루 신규 20개 블록. 일차 표시 필요) |
| VOCA-FR-012 | 한 장씩 영단어 → 뜻 보기 | 미구현 (현재는 4지선다 학습) |
| VOCA-FR-013 | 전날 단어와 자주 틀린 단어 섞기 | 부분 (전날 복습 블록 구현. 자주 틀린 단어 기준 없음) |
| VOCA-FR-014 | 암기 이력 DB 저장 | 부분 (답안 단위로 저장. 일차 정보는 없음) |
| VOCA-FR-021~026 | 시험 (문제 수, 방향, 형식, 채점, 이력) | 미구현 |
| VOCA-FR-031 | 진도 현황 | 부분 (홈 화면 집계) |
| VOCA-FR-032 | 날짜별 정답률 추이 | 구현 (보고서 화면) |
| VOCA-FR-033 | 자주 틀리는 단어 상위 N개 | 미구현 |
| VOCA-FR-034 | 통계를 DB 이력으로 계산 | 구현 |

도전 기능(VOCA-FR-041~062: 로그인, 다른 계정 이력, 설정)은 아직 없습니다.

## 프로젝트 구조

```
src/            Flask 앱 (app.py, db.py, *_service.py, templates/, static/)
data/           기초 단어 CSV (words_public.csv). DB 파일은 Git에 올리지 않음
tests/          단위 테스트 (unittest)
docs/           승인된 설계·분석 산출물
ai-agent/       작업 기록, 화면 점검, 참고자료
Dockerfile      서버 배포용 이미지 정의
```

## 테스트

```bash
python -m unittest discover -s tests
```
