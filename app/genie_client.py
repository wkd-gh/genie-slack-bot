import httpx
import asyncio
import os


class GenieClient:

    @property
    def base_url(self):
        host = os.getenv("DATABRICKS_HOST")
        space_id = os.getenv("GENIE_SPACE_ID")
        return f"https://{host}/api/2.0/genie/spaces/{space_id}"

    @property
    def headers(self):
        token = os.getenv("DATABRICKS_TOKEN")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def ask(self, question: str) -> dict:
        """
        Genie API에 질문하고 답변 반환
        Returns: {
            "text": str | None,
            "query": {"sql": str, "description": str} | None,
            "query_result": [{"col": "val", ...}] | None,
            "suggested_questions": [str],
            "error": str | None,  # "rate_limit" | "timeout" | 기타 에러 메시지
        }
        """
        async with httpx.AsyncClient(timeout=120.0) as client:

            # 1. 새 대화 시작
            response = await client.post(
                f"{self.base_url}/start-conversation",
                headers=self.headers,
                json={"content": question},
            )

            # 429 Rate Limit 처리
            if response.status_code == 429:
                return {"error": "rate_limit", "text": None, "query": None, "query_result": None, "suggested_questions": []}

            response.raise_for_status()
            data = response.json()

            conversation_id = data["conversation_id"]
            message_id = data["message_id"]

            # 2. 답변 완료될 때까지 폴링
            return await self._poll_message(client, conversation_id, message_id)

    async def _poll_message(
        self, client: httpx.AsyncClient, conversation_id: str, message_id: str
    ) -> dict:
        """답변이 완료될 때까지 폴링"""
        max_attempts = 30
        for _ in range(max_attempts):
            response = await client.get(
                f"{self.base_url}/conversations/{conversation_id}/messages/{message_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status == "COMPLETED":
                return await self._parse_response(client, conversation_id, message_id, data)
            elif status in ("FAILED", "CANCELLED"):
                return {
                    "error": data.get("error", "알 수 없는 오류"),
                    "text": None, "query": None, "query_result": None, "suggested_questions": []
                }

            await asyncio.sleep(2)

        return {"error": "timeout", "text": None, "query": None, "query_result": None, "suggested_questions": []}

    async def _parse_response(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        message_id: str,
        data: dict,
    ) -> dict:
        """COMPLETED 응답 파싱"""
        result = {
            "text": None,
            "query": None,
            "query_result": None,
            "suggested_questions": [],
            "error": None,
        }

        for attachment in data.get("attachments", []):
            attachment_id = attachment.get("attachment_id", "")

            # 텍스트 답변
            if "text" in attachment:
                result["text"] = attachment["text"].get("content", "")

            # 쿼리 (SQL + 설명)
            elif "query" in attachment:
                query = attachment["query"]
                result["query"] = {
                    "sql": query.get("query", ""),
                    "description": query.get("description", ""),
                    "title": query.get("title", ""),
                }
                # 쿼리 결과 별도 API 호출
                result["query_result"] = await self._fetch_query_result(
                    client, conversation_id, message_id, attachment_id
                )

            # 추천 질문
            elif "suggested_questions" in attachment:
                result["suggested_questions"] = attachment["suggested_questions"].get("questions", [])

        return result

    async def _fetch_query_result(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        message_id: str,
        attachment_id: str,
    ) -> list:
        """쿼리 결과 가져오기 (별도 API 호출)"""
        try:
            url = f"{self.base_url}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/query-result"
            # print(f"DEBUG query-result URL: {url}")
            response = await client.get(url, headers=self.headers)
            # print(f"DEBUG query-result status: {response.status_code}")
            # print(f"DEBUG query-result response: {response.text}")

            if response.status_code != 200:
                return []

            data = response.json()
            statement_response = data.get("statement_response", {})
            columns = [
                col["name"]
                for col in statement_response
                .get("manifest", {})
                .get("schema", {})
                .get("columns", [])
            ]
            rows_raw = statement_response.get("result", {}).get("data_array", [])

            rows = []
            for row in rows_raw:
                rows.append(dict(zip(columns, row)))

            return rows

        except Exception as e:
            print(f"DEBUG query-result error: {e}")
            import traceback
            traceback.print_exc()
            return []