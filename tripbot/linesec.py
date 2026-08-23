"""webhook 簽章簽章驗證（獨立成模組以便離線測試）。

依【03】§6.1：x-line-signature = base64(HMAC-SHA256(channelSecret, rawBody))。
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def verify_signature(channel_secret: str, raw_body: bytes,
                     signature_header: str) -> bool:
    if not (channel_secret and signature_header):
        return False
    digest = hmac.new(
        channel_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature_header)
