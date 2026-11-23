"""GET-only HTTP. This module has no POST method."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from brand_engage.safety import SafetyError, assert_x_read_url, public_error

USER_AGENT = "brand-engage/0.1 (drafts only; no writes)"


class RateLimitError(RuntimeError):
    pass


class AuthError(RuntimeError):
    pass


class XError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise SafetyError("Refused an HTTP redirect on an X read.")


def _default_open(req: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(req, timeout=timeout)


class HttpGet:
    def __init__(self, opener: Callable[..., Any] | None = None) -> None:
        self._open = opener or _default_open

    def get_json(
        self,
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
        *,
        timeout: float = 30,
    ) -> dict[str, Any]:
        assert_x_read_url(url)
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        full = f"{url}?{query}" if query else url
        # Re-check the path after encoding. The query string must not change the path.
        assert_x_read_url(full.split("?", 1)[0])
        request = urllib.request.Request(
            full,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers},
            method="GET",
        )
        try:
            with self._open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except SafetyError:
            raise
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise interpret_http_error(exc.code, body) from None
        except urllib.error.URLError as exc:
            raise XError(f"X request failed. {public_error(exc)}") from None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise XError("X returned a response that was not JSON.") from exc
        if not isinstance(payload, dict):
            raise XError("X returned a JSON value that was not an object.")
        return payload


def interpret_http_error(code: int, body: str) -> Exception:
    if code == 429:
        return RateLimitError("X rate limit reached. Search stopped.")
    if code == 401:
        return AuthError("X rejected the bearer token.")
    if code == 402:
        return AuthError("X returned 402. The app is out of API credits.")
    if code == 403:
        return AuthError("X returned 403. This bearer token cannot read recent search.")
    if code == 400:
        return XError(f"X rejected the query. {public_error(RuntimeError(body))[:200]}")
    return XError(f"X returned HTTP {code}.")
