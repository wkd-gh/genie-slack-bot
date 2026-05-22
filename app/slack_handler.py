import hmac
import hashlib
import time
import os
import ssl
import sqlparse
from tabulate import tabulate
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


def _loading_blocks(user_id: str, question: str) -> list:
    """처리 중 블록"""
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*<@{user_id}>님의 질문*\n> {question}"}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Databricks 테이블 분석 중 :loading-dots:"}
        }
    ]


def _format_table(rows: list, max_chars: int = 2500) -> str:
    if not rows:
        return ""

    total_rows = len(rows)
    for limit in range(min(20, total_rows), 0, -1):
        table = tabulate(
            [list(row.values()) for row in rows[:limit]],
            headers=list(rows[0].keys()),
            tablefmt="simple",
        )
        if len(table) <= max_chars:
            if limit < total_rows:
                table += f"\n... 외 {total_rows - limit}개 행"
            return table

    return "결과가 너무 길어 표시할 수 없어요."

# def _format_table(rows: list, max_rows: int = 10) -> str:
#     if not rows:
#         return ""
    
#     display_rows = rows[:max_rows]
#     table = tabulate(
#         [list(row.values()) for row in display_rows],
#         headers=list(rows[0].keys()),
#         tablefmt="simple",  # 슬랙 코드블록에서 가장 깔끔
#     )
    
#     if len(rows) > max_rows:
#         table += f"\n... 외 {len(rows) - max_rows}개 행"
    
#     return table

def _format_sql(sql: str) -> str:
    return sqlparse.format(
        sql,
        reindent=True,
        keyword_case="upper",
        indent_width=2,
    )

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
                "text": ":snad-clock: *요청이 너무 많습니다.*\n잠시 후 다시 시도해주세요. (분당 5개 질문 제한 - Free Edition)"
            }
        })
        return blocks

    # ── Timeout ───────────────────────────────────────
    if result.get("error") == "timeout":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":loading-mac: 응답 시간이 초과됐어요. 다시 시도해주세요."}
        })
        return blocks

    # ── 일반 에러 ─────────────────────────────────────
    if result.get("error"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":alert: 오류가 발생했어요:\n```{result['error']}```"}
        })
        return blocks

    # ── 텍스트 답변 ───────────────────────────────────
    if result.get("text"):
        quoted_text = "\n> ".join(result['text'].split('\n'))
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":genie-gif: *Genie의 답변*\n> {quoted_text}"}
        })

    # ── 쿼리 + 결과 ───────────────────────────────────
    if result.get("query"):
        query = result["query"]
        blocks.append({"type": "divider"})

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*생성된 SQL*\n```{_format_sql(query.get('sql', ''))}```"}
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

        if query.get("description"):
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":old-man-yells-at-databricks: _{query['description']}_"
                    }
                ]
            })

    # ── 추천 질문 ─────────────────────────────────────
    if result.get("suggested_questions"):
        blocks.append({"type": "divider"})
        questions_text = "\n".join(f"• {q}" for q in result["suggested_questions"])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":eyes-gif: *추가로 분석해 볼 만한 질문들*\n{questions_text}"
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
            text=":question-face: 질문을 입력해주세요.\n예: `/지니 오늘 거래량 상위 종목은?`",
        )
        return

    # 1. 처리 중 메시지 전송
    response = await slack_client.chat_postMessage(
        channel=channel_id,
        blocks=_loading_blocks(user_id, text),
        text="Databricks 테이블 분석 중 :loading-dots:",
    )
    msg_ts = response["ts"]

    try:
        result = await genie_client.ask(text)
        blocks = _build_blocks(user_id, text, result)

        # 2. 같은 메시지를 결과로 업데이트
        await slack_client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            blocks=blocks,
            text=result.get("text") or "Genie 답변",
        )
    except Exception as e:
        await slack_client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*<@{user_id}>님의 질문*\n> {text}"}
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":alert: 오류가 발생했어요: {str(e)}"}
                }
            ],
            text=f"오류: {str(e)}",
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
            text=":question-face: 질문을 입력해주세요.\n예: `@Databricks Genie 오늘 거래량 상위 종목은?`",
        )
        return

    # 1. 처리 중 메시지 전송 (스레드에)
    response = await slack_client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=_loading_blocks(user_id, text),
        text="Databricks 테이블 분석 중 :loading-dots:",
    )
    msg_ts = response["ts"]

    try:
        result = await genie_client.ask(text)
        blocks = _build_blocks(user_id, text, result)

        # 2. 같은 메시지를 결과로 업데이트
        await slack_client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            blocks=blocks,
            text=result.get("text") or "Genie 답변",
        )
    except Exception as e:
        await slack_client.chat_update(
            channel=channel_id,
            ts=msg_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*<@{user_id}>님의 질문*\n> {text}"}
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":alert: 오류가 발생했어요: {str(e)}"}
                }
            ],
            text=f"오류: {str(e)}",
        )