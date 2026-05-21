import hmac
import hashlib
import time
import os
from slack_sdk.web.async_client import AsyncWebClient
from app.genie_client import GenieClient

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")      # xoxb-...
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")

slack_client = AsyncWebClient(token=SLACK_BOT_TOKEN)
genie_client = GenieClient()


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Slack 요청 서명 검증"""
    # 5분 이상 지난 요청 거부 (replay attack 방지)
    if abs(time.time() - int(timestamp)) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


async def handle_slash_command(
    user_id: str,
    text: str,
    channel_id: str,
    response_url: str,
):
    """
    슬랙 슬래시 커맨드 처리
    - Genie API 호출
    - 스레드에 답변
    """
    if not text.strip():
        await slack_client.chat_postMessage(
            channel=channel_id,
            text="❓ 질문을 입력해주세요.\n예: `/지니 오늘 거래량 상위 종목은?`",
        )
        return

    # 처리 중 메시지 전송 (스레드 부모 메시지)
    response = await slack_client.chat_postMessage(
        channel=channel_id,
        text=f"<@{user_id}>님의 질문: *{text}*\n\n⏳ Genie가 분석 중이에요...",
    )
    thread_ts = response["ts"]

    try:
        # Genie API 호출
        answer = await genie_client.ask(text)

        # 스레드에 답변
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=answer,
        )

    except Exception as e:
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"❌ 오류가 발생했어요: {str(e)}",
        )
