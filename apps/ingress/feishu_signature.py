from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import HTTPException, Request

from aiop.settings import get_settings


async def verify_feishu_signature(request: Request) -> bytes:
    """Verify Feishu webhook signature using app_secret. Returns the raw body for downstream use."""
    s = get_settings()
    body = await request.body()

    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")

    if not (timestamp and nonce and signature) or not s.feishu_app_secret:
        # In dev mode without signature, accept; production should fail closed.
        return body

    raw = (timestamp + nonce + s.feishu_app_secret).encode() + body
    computed = base64.b64encode(hmac.new(s.feishu_app_secret.encode(), raw, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=401, detail="invalid feishu signature")
    return body
