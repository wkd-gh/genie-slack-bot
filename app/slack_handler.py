import hmac
import hashlib
import time
import os
import ssl
from slack_sdk.web.async_client import AsyncWebClient
from app.genie_client import GenieClient

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

genie_client = GenieClient()


def _get_slack_client() -> AsyncWebClient:
    """요청 시점에 토큰을 읽어서 클라이언트 생성"""
    return AsyncWebClient(token=os.getenv("SLACK_BOT_TOKEN"), ssl=ssl_context)


def verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Slack 요청 서명 검증"""
    slack_signing_secret = os.getenv("SLACK_SIGNING_SECRET")

    if not timestamp or not signature or not slack_signing_secret:
        return False

    try:
        if abs(time.time() - int(timestamp)) > 600:
            return False
    except ValueError:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        slack_signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def _format_table(rows: list, max_rows: int = 10) -> str:
    """쿼리 결과를 고정폭 텍스트 테이블로 포맷"""
    if not rows:
        return ""

    columns = list(rows[0].keys())
    col_widths = {col: len(col) for col in columns}
    for row in rows[:max_rows]:
        for col in columns:
            col_widths[col] = max(col_widths[col], len(str(row.get(col, ""))))

    header    = " | ".join(col.ljust(col_widths[col]) for col in columns)
    separator = "-+-".join("-" * col_widths[col] for col in columns)
    lines = [header, separator]

    for row in rows[:max_rows]:
        line = " | ".join(str(row.get(col, "")).ljust(col_widths[col]) for col in columns)
        lines.append(line)

    if len(rows) > max_rows:
        lines.append(f"... 외 {len(rows) - max_rows}개 행")

    return "\n".join(lines)


def _build_blocks(user_id: str, question: str, result: dict) -> list:
    """Slack Block Kit 메시지 구성"""
    blocks = []

    # ── 헤더 ──────────────────────────────────────────
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*<@{user_id}>님의 질문*\n> {question}"
        }
    })
    blocks.append({"type": "divider"})

    # ── Rate Limit ────────────────────────────────────
    if result.get("error") == "rate_limit":
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "⏳ *요청이 너무 많아요!*\n잠시 후 다시 시도해주세요. (분당 5개 질문 제한)"
            }
        })
        return blocks

    # ── Timeout ───────────────────────────────────────
    if result.get("error") == "timeout":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "⏱️ 응답 시간이 초과됐어요. 다시 시도해주세요."}
        })
        return blocks

    # ── 일반 에러 ─────────────────────────────────────
    if result.get("error"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"❌ 오류가 발생했어요:\n```{result['error']}```"}
        })
        return blocks

    # ── 텍스트 답변 ───────────────────────────────────
    if result.get("text"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"🧞 *Genie의 답변*\n{result['text']}"}
        })

    # ── 쿼리 + 결과 ───────────────────────────────────
    if result.get("query"):
        query = result["query"]
        blocks.append({"type": "divider"})

        if query.get("description"):
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📊 *{query['description']}*"}
            })

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*생성된 SQL*\n```{query.get('sql', '')}```"}
        })

        rows = result.get("query_result") or []
        if rows:
            table_text = _format_table(rows)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*조회 결과*\n```{table_text}```"}
            })
        else:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_조회 결과가 없거나 가져오지 못했어요._"}
            })

    # ── 추천 질문 ─────────────────────────────────────
    if result.get("suggested_questions"):
        blocks.append({"type": "divider"})
        questions_text = "\n".join(f"• {q}" for q in result["suggested_questions"])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"💡 *이런 것도 물어볼 수 있어요*\n{questions_text}"
            }
        })

    return blocks


async def handle_slash_command(
    user_id: str,
    text: str,
    channel_id: str,
    response_url: str,
):
    """슬래시 커맨드 처리"""
    slack_client = _get_slack_client()

    if not text.strip():
        await slack_client.chat_postMessage(
            channel=channel_id,
            text="❓ 질문을 입력해주세요.\n예: `/지니 오늘 거래량 상위 종목은?`",
        )
        return

    # 처리 중 메시지 (스레드 부모)
    response = await slack_client.chat_postMessage(
        channel=channel_id,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*<@{user_id}>님의 질문*\n> {text}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "⏳ Genie가 분석 중이에요..."}
            }
        ],
        text=f"{text} - 분석 중...",
    )
    thread_ts = response["ts"]

    try:
        result = await genie_client.ask(text)
        blocks = _build_blocks(user_id, text, result)
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=result.get("text") or "Genie 답변",
        )
    except Exception as e:
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"❌ 오류가 발생했어요: {str(e)}",
        )


async def handle_mention(
    user_id: str,
    text: str,
    channel_id: str,
    thread_ts: str,
):
    """@멘션 처리"""
    slack_client = _get_slack_client()

    if not text.strip():
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="❓ 질문을 입력해주세요.\n예: `@Databricks Genie 오늘 거래량 상위 종목은?`",
        )
        return

    await slack_client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*<@{user_id}>님의 질문*\n> {text}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "⏳ Genie가 분석 중이에요..."}
            }
        ],
        text=f"{text} - 분석 중...",
    )

    try:
        result = await genie_client.ask(text)
        print(f"DEBUG mention result: {result}")
        blocks = _build_blocks(user_id, text, result)
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=result.get("text") or "Genie 답변",
        )
    except Exception as e:
        print(f"DEBUG mention error: {e}")
        import traceback
        traceback.print_exc()
        await slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"❌ 오류가 발생했어요: {str(e)}",
        )