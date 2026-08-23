from __future__ import annotations

import base64
import hashlib
import hmac

from tripbot.linesec import verify_signature


def test_valid_signature() -> None:
    secret = "channel-secret"
    body = b'{"events":[]}'
    good = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    assert verify_signature(secret, body, good) is True


def test_invalid_signature() -> None:
    assert verify_signature("s", b"body", "bad-signature") is False
    assert verify_signature("", b"body", "x") is False
    assert verify_signature("s", b"body", "") is False
