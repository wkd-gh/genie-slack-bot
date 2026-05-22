from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from app.slack_handler import verify_slack_signature, handle_slash_command, handle_mention

app = FastAPI(title="Genie Slack Bot")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/slack/sql-ask")
async def sql_ask(request: Request, background_tasks: BackgroundTasks):
    """
    Slack Slash Command /지니 엔드포인트
    - Slack 서명 검증
    - 즉시 200 응답 (3초 제한)
    - 백그라운드에서 Genie API 호출 후 스레드 답변
    """

    # challenge 검증 먼저 확인
    try:
        body_json = await request.json()
        if body_json.get("type") == "url_verification":
            return {"challenge": body_json.get("challenge")}
    except:
        pass

    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    # Slack 서명 검증
    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Form 데이터 파싱
    form = await request.form()
    user_id = form.get("user_id", "")
    text = form.get("text", "")
    channel_id = form.get("channel_id", "")
    response_url = form.get("response_url", "")

    # 백그라운드에서 처리 (Slack 3초 제한 우회)
    background_tasks.add_task(
        handle_slash_command,
        user_id=user_id,
        text=text,
        channel_id=channel_id,
        response_url=response_url,
    )

    # Slack에 즉시 빈 응답 (처리 중 메시지는 background에서 전송)
    return {"response_type": "in_channel", "text": ""}

@app.post("/slack/mention")
async def mention(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Slack URL 검증 (최초 1회)
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Slack 서명 검증
    if not verify_slack_signature(raw_body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = body.get("event", {})
    event_type = event.get("type")

    if event_type == "app_mention":
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")
        # 봇 멘션 텍스트 제거 (<@BOTID> 부분)
        raw_text = event.get("text", "")
        text = " ".join(
            word for word in raw_text.split()
            if not word.startswith("<@")
        ).strip()

        background_tasks.add_task(
            handle_mention,
            user_id=user_id,
            text=text,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )

    return {"ok": True}
