# Genie Slack Bot

> Databricks Genie에게 자연어로 물어보면 SQL을 짜고 데이터를 가져다줍니다.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![Databricks](https://img.shields.io/badge/Databricks-Genie-FF3621?style=flat-square&logo=databricks&logoColor=white)
![Slack](https://img.shields.io/badge/Slack-Bot-4A154B?style=flat-square&logo=slack&logoColor=white)
![Cloud Run](https://img.shields.io/badge/Google_Cloud-Cloud_Run-4285F4?style=flat-square&logo=googlecloud&logoColor=white)

---

## Overview

Slack에서 두 가지 방식으로 Databricks Genie에게 질문할 수 있습니다.

**슬래시 커맨드**
```
/지니 SK하이닉스 최근 5일 종가 알려줘
```

**@멘션**
```
@Databricks SK하이닉스 최근 5일 종가 알려줘
```

Genie가 SQL을 생성하고 데이터를 조회해서 스레드로 답변해줍니다.

```
🧞 Genie의 답변
SK하이닉스(000660)의 최근 5일 종가입니다.

📊 SK하이닉스 최근 5일 종가

생성된 SQL
SELECT date, close_price FROM stock_prices WHERE ticker = '000660' ORDER BY date DESC LIMIT 5

조회 결과
date       | close_price
-----------+------------
2026-05-21 | 75400
2026-05-20 | 74500
...

💡 이런 것도 물어볼 수 있어요
• 삼성전자 이번 달 평균 거래량은?
• 코스피 상위 10개 종목 오늘 등락률은?
```

---

## Architecture

```
Slack (슬래시 커맨드 or @멘션)
      │
      ▼
FastAPI (Cloud Run)
      │  ① 즉시 "분석 중..." 응답 (Slack 3초 제한 준수)
      │  ② 백그라운드에서 Genie API 호출
      ▼
Databricks Genie API
      │  start-conversation → 폴링 (2초 간격, 최대 30회/60초)
      │  COMPLETED 시 쿼리 결과 별도 API 호출
      ▼
FastAPI → "분석 중..." 메시지를 Block Kit 결과로 인플레이스 업데이트
```

### 응답 구조

Genie 응답은 아래 4가지 요소로 구성됩니다.

| 요소 | 설명 |
|------|------|
| `text` | 자연어 답변 텍스트 (Markdown → Slack mrkdwn 자동 변환) |
| `query` | 생성된 SQL + 설명 (sqlparse로 포맷팅) |
| `query_result` | 실제 쿼리 조회 결과 (최대 2500자 기준 행 수 자동 조절) |
| `suggested_questions` | Genie가 제안하는 추천 질문 목록 |
| `error` | 에러 유형: `rate_limit` / `timeout` / 기타 메시지 |

### 에러 처리

| 상황 | 메시지 |
|------|--------|
| `rate_limit` (429) | "요청이 너무 많습니다. 잠시 후 다시 시도해주세요." |
| `timeout` (60초 초과) | "응답 시간이 초과됐어요. 다시 시도해주세요." |
| `FAILED` / `CANCELLED` | Genie 오류 메시지 표시 |
| 빈 질문 | 예시 문구와 함께 안내 메시지 전송 |

---

## Project Structure

```
genie-slack-bot/
├── app/
│   ├── main.py           # FastAPI 엔트리포인트 & 라우터
│   ├── slack_handler.py  # Slack 서명 검증, 메시지 포맷, 핸들러
│   └── genie_client.py   # Databricks Genie API 클라이언트
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

### 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /health` | 헬스 체크 |
| `POST /slack/sql-ask` | 슬래시 커맨드 `/지니` 처리 |
| `POST /slack/mention` | `@멘션` 이벤트 처리 |

---

## Environment Variables

`.env.example`을 참고하여 `.env` 파일을 생성하세요.

| 변수명 | 설명 |
|--------|------|
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Slack App Signing Secret |
| `DATABRICKS_HOST` | Databricks Workspace 호스트 (`dbc-xxxx.cloud.databricks.com`) |
| `DATABRICKS_TOKEN` | Databricks Personal Access Token (`dapi...`) |
| `GENIE_SPACE_ID` | Databricks Genie Space ID |

---

## Getting Started

### 로컬 실행

```bash
# 1. 레포 클론
git clone https://github.com/Money-Digger/genie-slack-bot.git
cd genie-slack-bot

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일에 실제 값 채우기

# 4. 서버 실행
uvicorn app.main:app --reload --port 8000  # 터미널 1

ngrok http 8000                             # 터미널 2 (ngrok 터널)
```

### Cloud Run 배포

```bash
gcloud run deploy genie-slack-bot \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --set-env-vars SLACK_BOT_TOKEN=...,SLACK_SIGNING_SECRET=...,DATABRICKS_HOST=...,DATABRICKS_TOKEN=...,GENIE_SPACE_ID=...
```

---

## Slack App 설정

### 1. Slash Command

**Slash Commands** → `/지니` 추가
- Request URL: `https://{CLOUD_RUN_URL}/slack/sql-ask`

### 2. @멘션 (Event Subscriptions)

**Event Subscriptions** 활성화
- Request URL: `https://{CLOUD_RUN_URL}/slack/mention`
- Subscribe to bot events → `app_mention` 추가

### 3. OAuth & Permissions

Bot Token Scopes 추가:

| Scope | 용도 |
|-------|------|
| `chat:write` | 메시지 전송 |
| `chat:write.public` | 봇이 참여하지 않은 채널에도 전송 (선택) |
| `app_mentions:read` | @멘션 이벤트 수신 |

### 4. 워크스페이스에 앱 설치

---

## Related

- [airflow-etl-pipeline](https://github.com/Money-Digger/airflow-etl-pipeline) — 데이터 수집 및 Databricks 적재 파이프라인
- [genie-web-app](https://github.com/Money-Digger/genie-web-app.git) — Databricks Genie 웹 애플리케이션