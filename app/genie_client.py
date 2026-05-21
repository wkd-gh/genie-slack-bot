import httpx
import asyncio
import os

DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")       # dbc-xxxx.cloud.databricks.com
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")      # dapi...
GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID")          # Genie Space ID


class GenieClient:
    def __init__(self):
        self.base_url = f"https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{GENIE_SPACE_ID}"
        self.headers = {
            "Authorization": f"Bearer {DATABRICKS_TOKEN}",
            "Content-Type": "application/json",
        }

    async def ask(self, question: str) -> str:
        """
        Genie API에 질문하고 답변 반환
        1. 새 대화 시작
        2. 답변 폴링
        3. 결과 반환
        """
        async with httpx.AsyncClient(timeout=120.0) as client:

            # 1. 새 대화 시작
            response = await client.post(
                f"{self.base_url}/start-conversation",
                headers=self.headers,
                json={"content": question},
            )
            response.raise_for_status()
            data = response.json()

            conversation_id = data["conversation_id"]
            message_id = data["message_id"]

            # 2. 답변 완료될 때까지 폴링
            result = await self._poll_message(client, conversation_id, message_id)
            return result

    async def _poll_message(
        self, client: httpx.AsyncClient, conversation_id: str, message_id: str
    ) -> str:
        """답변이 완료될 때까지 폴링"""
        max_attempts = 30  # 최대 60초 대기
        for _ in range(max_attempts):
            response = await client.get(
                f"{self.base_url}/conversations/{conversation_id}/messages/{message_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()

            status = data.get("status")

            if status == "COMPLETED":
                return self._extract_answer(data)
            elif status in ("FAILED", "CANCELLED"):
                return f"❌ 질문 처리 실패: {data.get('error', '알 수 없는 오류')}"

            await asyncio.sleep(2)

        return "⏱️ 응답 시간이 초과됐어요. 다시 시도해주세요."

    def _extract_answer(self, data: dict) -> str:
        """응답 데이터에서 답변 텍스트 추출"""
        attachments = data.get("attachments", [])

        for attachment in attachments:
            # 텍스트 답변
            if attachment.get("type") == "text":
                return attachment.get("content", "")

            # 쿼리 결과 테이블
            if attachment.get("type") == "query":
                query = attachment.get("query", {})
                description = query.get("description", "")
                sql = query.get("query", "")
                result = self._format_query_result(attachment.get("query_result", {}))
                return f"{description}\n\n```sql\n{sql}\n```\n\n{result}"

        return data.get("content", "답변을 가져올 수 없어요.")

    def _format_query_result(self, query_result: dict) -> str:
        """쿼리 결과를 테이블 형식으로 포맷"""
        if not query_result:
            return ""

        columns = [col["name"] for col in query_result.get("statement_response", {}).get("manifest", {}).get("schema", {}).get("columns", [])]
        rows = query_result.get("statement_response", {}).get("result", {}).get("data_typed_array", [])

        if not columns or not rows:
            return ""

        # 헤더
        header = " | ".join(columns)
        separator = " | ".join(["---"] * len(columns))
        lines = [header, separator]

        # 데이터 행 (최대 20행)
        for row in rows[:20]:
            values = [str(v.get("str", "")) for v in row.get("values", [])]
            lines.append(" | ".join(values))

        if len(rows) > 20:
            lines.append(f"_... 외 {len(rows) - 20}개 행_")

        return "\n".join(lines)
