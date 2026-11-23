"""Deliver the digest to Aden's private Slack channel.

This is the only Slack call, and it can only hit an incoming webhook.
It does not read Slack, and it cannot post anywhere else.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from brand_engage.safety import SafetyError, assert_slack_webhook, public_error


def send_digest(webhook_url: str, text: str, *, transport=None) -> None:
    assert_slack_webhook(webhook_url)
    if len(text) > 39000:
        text = text[:38900].rstrip() + "\n\n(Truncated.)"
    payload = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    opener = transport or urllib.request.urlopen
    try:
        with opener(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            if status >= 300:
                raise RuntimeError(f"Slack returned HTTP {status}.")
    except SafetyError:
        raise
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Slack returned HTTP {exc.code}.") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Slack request failed. {public_error(exc)}") from None
