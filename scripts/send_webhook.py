"""Send signed sample Zendesk webhooks to a running triage service (stdlib only).

    python scripts/send_webhook.py            # one random sample
    python scripts/send_webhook.py --all      # every sample
    python scripts/send_webhook.py --url https://my-app.fly.dev/webhooks/zendesk
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.samples import SAMPLE_TICKETS  # noqa: E402


def send(url: str, payload: dict, secret: str | None) -> None:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sig = base64.b64encode(hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()).decode()
        headers |= {"X-Zendesk-Webhook-Signature": sig, "X-Zendesk-Webhook-Signature-Timestamp": ts}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        print(f"#{payload['ticket_id']} {payload['subject'][:50]!r:55} -> {resp.status} {resp.read().decode()}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000/webhooks/zendesk")
    p.add_argument("--secret", default=os.getenv("ZENDESK_WEBHOOK_SECRET"))
    p.add_argument("--all", action="store_true")
    args = p.parse_args()
    for t in SAMPLE_TICKETS if args.all else [random.choice(SAMPLE_TICKETS)]:
        send(args.url, {**t, "ticket_id": str(t["ticket_id"])}, args.secret)


if __name__ == "__main__":
    main()
