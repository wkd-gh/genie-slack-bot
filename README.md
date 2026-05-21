# Genie Slack Bot

> Databricks Genie에게 자연어로 물어보면 SQL을 짜고 데이터를 가져다줍니다.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![Databricks](https://img.shields.io/badge/Databricks-Genie-FF3621?style=flat-square&logo=databricks&logoColor=white)
![Slack](https://img.shields.io/badge/Slack-Bot-4A154B?style=flat-square&logo=slack&logoColor=white)
![Cloud Run](https://img.shields.io/badge/Google_Cloud-Cloud_Run-4285F4?style=flat-square&logo=googlecloud&logoColor=white)

---

## Overview

Slack에서 `/지니 오늘 거래량 상위 종목은?` 한 마디면,
Databricks Genie가 SQL을 생성하고 데이터를 조회해서 스레드로 답변해줍니다.

```
/지니 SK하이닉스 최근 5일 종가 알려줘
```

```
📊 SK하이닉스 (000660) 최근 5일 종가

| 날짜       | 종가    | 등락률  |
|------------|---------|---------|
| 2026-05-21 | 75,400  | +1.21%  |
| 2026-05-20 | 74,500  | -0.53%  |
| ...
```

---

## Architecture

```
Slack (/지니 질문)
      │
      ▼
FastAPI (Cloud Run)
      │  ① 즉시 "분석 중..." 응답
      │  ② 백그라운드에서 Genie API 호출
      ▼
Databricks Genie API
      │  Text2SQL → 쿼리 실행 → 결과 반환
      ▼
FastAPI → Slack 스레드에 답변
```

---

## Project Structure

```
genie-slack-bot/
├── app/
│   ├── main.py           # FastAPI 엔트리포인트 & 라우터
│   ├── slack_handler.py  # Slack 서명 검증 & 메시지 처리
│   └── genie_client.py   # Databricks Genie API 클라이언트
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Environment Variables

`.env.example`을 참고하여 `.env` 파일을 생성하세요.

| 변수명 | 설명 |
|--------|------|
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Slack App Signing Secret |
| `DATABRICKS_HOST` | Databricks Workspace URL (`dbc-xxxx.cloud.databricks.com`) |
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
uvicorn app.main:app --reload --port 8000
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

1. [api.slack.com](https://api.slack.com)에서 앱 생성
2. **Slash Commands** → `/지니` 추가
   - Request URL: `https://{CLOUD_RUN_URL}/slack/sql-ask`
3. **OAuth & Permissions** → Bot Token Scopes 추가
   - `chat:write`
   - `chat:write.public` (선택)
4. 워크스페이스에 앱 설치

---

## Related

- [airflow-etl-pipeline](https://github.com/Money-Digger/airflow-etl-pipeline) — 데이터 수집 및 Databricks 적재 파이프라인