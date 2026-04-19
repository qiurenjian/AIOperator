from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from aiop.settings import get_settings

FEISHU_BASE = "https://open.feishu.cn/open-apis"


@dataclass
class _Token:
    value: str
    expires_at: float


class FeishuClient:
    """Minimal async wrapper for Feishu REST APIs we need in P0/P1."""

    def __init__(self, app_id: str | None = None, app_secret: str | None = None) -> None:
        s = get_settings()
        self.app_id = app_id or s.feishu_app_id
        self.app_secret = app_secret or s.feishu_app_secret
        self._token: _Token | None = None
        self._client = httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _tenant_token(self) -> str:
        now = time.time()
        if self._token and self._token.expires_at - now > 60:
            return self._token.value
        r = await self._client.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(f"feishu token error: {body}")
        self._token = _Token(value=body["tenant_access_token"], expires_at=now + body["expire"])
        return self._token.value

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = await self._tenant_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        r = await self._client.request(method, f"{FEISHU_BASE}{path}", headers=headers, **kwargs)
        r.raise_for_status()
        body = r.json()
        if body.get("code") not in (0, None):
            raise RuntimeError(f"feishu api {path} error: {body}")
        return body

    async def send_card(self, *, receive_id: str, receive_id_type: str, card: dict) -> dict:
        body = await self._request(
            "POST",
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            json={
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": _json_dumps(card),
            },
        )
        return body["data"]

    async def reply_text(self, *, message_id: str, text: str) -> dict:
        body = await self._request(
            "POST",
            f"/im/v1/messages/{message_id}/reply",
            json={"msg_type": "text", "content": _json_dumps({"text": text})},
        )
        return body["data"]

    async def bitable_upsert_record(
        self, *, app_token: str, table_id: str, fields: dict, search_field: str | None = None
    ) -> dict:
        if search_field and (key := fields.get(search_field)):
            search = await self._request(
                "POST",
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                json={"filter": {"conjunction": "and", "conditions": [
                    {"field_name": search_field, "operator": "is", "value": [str(key)]}
                ]}, "page_size": 1},
            )
            items = search.get("data", {}).get("items") or []
            if items:
                rec_id = items[0]["record_id"]
                upd = await self._request(
                    "PUT",
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{rec_id}",
                    json={"fields": fields},
                )
                return upd["data"]["record"]
        created = await self._request(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json={"fields": fields},
        )
        return created["data"]["record"]


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
