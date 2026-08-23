"""提醒訂閱的加密儲存與合併。

架構決策（README 有完整說明）：
- 公開 repo 不放 LINE userId 明文 → 訂閱資料以 Fernet 加密後存 data/subscriptions.enc。
- 寫入路徑：Vercel webhook 加密 payload → GitHub repository_dispatch →
  workflows/subs.yml 解密、合併、重新加密、commit。
- 讀取路徑：Vercel cron 以 SUBS_FERNET_KEY 解密，掃描到期訂閱 multicast。

檔案格式（解密後 JSON）：
{"version":1, "subs":[{"u":userId,"k":eventKey,"at":remindAtMs,"sent":false}]}
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet


def _fernet(key: str) -> Fernet:
    """接受 Fernet 原生 key；任意字串則以 SHA-256 衍生成合法 key。"""
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        import hashlib

        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def load_subs(path: str, key: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    token = p.read_text(encoding="utf-8").strip()
    if not token:
        return []
    data = json.loads(_fernet(key).decrypt(token.encode()))
    return [s for s in data.get("subs", []) if isinstance(s, dict)]


def save_subs(path: str, key: str, subs: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": 1, "subs": subs}, ensure_ascii=False)
    Path(path).write_text(
        _fernet(key).encrypt(payload.encode()).decode(), encoding="utf-8"
    )


def upsert(subs: list[dict], user_id: str, event_key: str,
           remind_at_ms: int) -> list[dict]:
    for s in subs:
        if s["u"] == user_id and s["k"] == event_key:
            s["at"] = remind_at_ms
            s["sent"] = False
            break
    else:
        subs.append(
            {"u": user_id, "k": event_key, "at": remind_at_ms, "sent": False}
        )
    return subs


def mark_sent(subs: list[dict], event_key: str, remind_at_ms: int) -> int:
    n = 0
    for s in subs:
        if s["k"] == event_key and s["at"] == remind_at_ms and not s.get("sent"):
            s["sent"] = True
            n += 1
    return n


def prune(subs: list[dict], max_age_days: int = 30) -> list[dict]:
    cutoff = (time.time() - max_age_days * 86400) * 1000
    keep: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for s in subs:
        ident = (s["u"], s["k"])
        if ident in seen or int(s.get("at", 0)) < cutoff:
            continue
        seen.add(ident)
        keep.append(s)
    return keep


# ---------- CLI（workflows/subs.yml 呼叫） ----------

def _cli() -> int:  # pragma: no cover - 由整合測試覆蓋
    import argparse

    parser = argparse.ArgumentParser(description="subscriptions.enc 維護工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    apply_p = sub.add_parser("apply", help="套用加密 blob 的變更並重寫檔案")
    apply_p.add_argument("--blob", required=True, help="webhook 送來的 Fernet token")
    apply_p.add_argument("--path", default="data/subscriptions.enc")

    prune_p = sub.add_parser("prune", help="清理過期訂閱")
    prune_p.add_argument("--path", default="data/subscriptions.enc")

    args = parser.parse_args()
    key = os.environ.get("SUBS_FERNET_KEY", "")
    if not key:
        print("SUBS_FERNET_KEY 未設定", flush=True)
        return 2

    subs = load_subs(args.path, key)
    if args.cmd == "apply":
        inner = json.loads(_fernet(key).decrypt(args.blob.encode()))
        op = inner.get("op")
        if op == "subscribe":
            subs = upsert(subs, inner["u"], inner["k"], int(inner["at"]))
        elif op == "unsubscribe":
            subs = [s for s in subs
                    if not (s["u"] == inner["u"] and s["k"] == inner["k"])]
        elif op == "mark-sent":
            mark_sent(subs, inner["k"], int(inner["at"]))
        else:
            print(f"未知操作 {op!r}", flush=True)
            return 2
        subs = prune(subs)
        save_subs(args.path, key, subs)
        print(f"OK subs={len(subs)} op={op}", flush=True)
        return 0

    before = len(subs)
    subs = prune(load_subs(args.path, key))
    save_subs(args.path, key, subs)
    print(f"pruned {before} -> {len(subs)}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
