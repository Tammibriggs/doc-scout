"""Small GitHub REST client that respects GitHub's rate limits.

GitHub has separate budgets per resource: ``core`` (5000/h with a token), ``search``
(30/min with a token, 10/min without) and ``code_search`` (10/min, token required).
Searches are paced proactively; exhausted budgets wait for the reset time from the
response headers, or raise :class:`RateLimited` when the wait would be too long.
"""

from __future__ import annotations

import base64
import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

import httpx

from docscout import __version__

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"
MAX_TARBALL_BYTES = 60 * 1024 * 1024

# Minimum seconds between calls, per resource, so searches never hit the per-minute cap.
_PACE_WITH_TOKEN = {"search": 2.1, "code_search": 6.5}
_PACE_WITHOUT_TOKEN = {"search": 6.5, "code_search": 6.5}


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status
        self.message = message


class AuthError(GitHubError):
    """The token is missing, expired or revoked (HTTP 401)."""


class NotFound(GitHubError):
    pass


class RateLimited(Exception):
    def __init__(self, resource: str, wait_seconds: float) -> None:
        super().__init__(f"GitHub {resource} rate limit: retry in {int(wait_seconds)}s")
        self.resource = resource
        self.wait_seconds = wait_seconds


class GitHub:
    def __init__(
        self,
        token: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        max_wait: float = 900,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"docscout/{__version__}",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.has_token = bool(token)
        self._client = httpx.Client(
            base_url=API_URL,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
            follow_redirects=True,
        )
        self._max_wait = max_wait
        self._sleep = sleep
        self._clock = clock
        self._pace = _PACE_WITH_TOKEN if token else _PACE_WITHOUT_TOKEN
        self._last_call: dict[str, float] = {}
        self.calls: Counter[str] = Counter()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHub:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core request

    def _wait_for_pace(self, resource: str) -> None:
        gap = self._pace.get(resource)
        last = self._last_call.get(resource)
        if gap and last is not None:
            remaining = gap - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)

    def _limit_wait(self, resp: httpx.Response) -> float | None:
        """Seconds to wait if this response is a rate-limit response, else None."""
        if resp.status_code not in (403, 429):
            return None
        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = float(resp.headers.get("X-RateLimit-Reset", "0"))
            return max(1.0, reset - self._clock() + 1)
        text = resp.text.lower()
        if "rate limit" in text:
            return 60.0  # secondary limit without Retry-After: GitHub asks for at least a minute
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        resource: str = "core",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        for attempt in range(5):
            self._wait_for_pace(resource)
            try:
                resp = self._client.request(method, path, params=params, headers=headers)
            except httpx.TransportError:
                if attempt == 4:
                    raise
                self._sleep(2**attempt)
                continue
            finally:
                self._last_call[resource] = self._clock()
            self.calls[resource] += 1

            if resp.status_code == 401:
                raise AuthError(401, _message(resp))
            wait = self._limit_wait(resp)
            if wait is not None:
                if wait > self._max_wait:
                    raise RateLimited(resource, wait)
                log.info("GitHub %s rate limit reached; waiting %ds", resource, int(wait))
                self._sleep(wait)
                continue
            if resp.status_code >= 500:
                self._sleep(2**attempt)
                continue
            if resp.status_code == 404:
                raise NotFound(404, _message(resp))
            if resp.status_code >= 400:
                raise GitHubError(resp.status_code, _message(resp))
            return resp
        raise GitHubError(resp.status_code, "gave up after repeated failures")

    def get_json(self, path: str, *, params: dict[str, Any] | None = None, resource: str = "core") -> Any:
        return self.request("GET", path, params=params, resource=resource).json()

    # ------------------------------------------------------------------ endpoints

    def rate_limit(self) -> dict[str, Any]:
        """Remaining budget per resource. This call does not count against the quota."""
        return self.get_json("/rate_limit", resource="rate_limit")["resources"]

    def search_repos(self, query: str, *, page: int = 1, per_page: int = 100, sort: str = "updated") -> tuple[int, list[dict]]:
        data = self.get_json(
            "/search/repositories",
            params={"q": query, "page": page, "per_page": per_page, "sort": sort, "order": "desc"},
            resource="search",
        )
        return data["total_count"], data["items"]

    def search_issues(self, query: str, *, page: int = 1, per_page: int = 100) -> tuple[int, list[dict]]:
        data = self.get_json(
            "/search/issues",
            params={"q": query, "page": page, "per_page": per_page, "sort": "updated", "order": "desc"},
            resource="search",
        )
        return data["total_count"], data["items"]

    def search_code(self, query: str, *, page: int = 1, per_page: int = 100) -> tuple[int, list[dict]]:
        if not self.has_token:
            raise AuthError(401, "code search requires a GitHub token")
        data = self.get_json(
            "/search/code", params={"q": query, "page": page, "per_page": per_page}, resource="code_search"
        )
        return data["total_count"], data["items"]

    def get_repo(self, full_name: str) -> dict[str, Any]:
        return self.get_json(f"/repos/{full_name}")

    def get_tree(self, full_name: str, ref: str) -> tuple[list[dict], bool]:
        """All files in the repo at ``ref``. The flag is True if GitHub truncated the listing."""
        data = self.get_json(f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"})
        return data.get("tree", []), bool(data.get("truncated"))

    def get_readme(self, full_name: str, max_bytes: int = 512 * 1024) -> str | None:
        try:
            data = self.get_json(f"/repos/{full_name}/readme")
        except NotFound:
            return None
        if data.get("size", 0) > max_bytes or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")

    def get_file(self, full_name: str, path: str, *, ref: str | None = None, max_bytes: int = 2 * 1024 * 1024) -> bytes | None:
        """Raw file content, or None if it is missing or larger than ``max_bytes``."""
        params = {"ref": ref} if ref else None
        try:
            resp = self.request(
                "GET",
                f"/repos/{full_name}/contents/{path}",
                params=params,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except NotFound:
            return None
        if len(resp.content) > max_bytes:
            return None
        return resp.content

    def get_languages(self, full_name: str) -> dict[str, int]:
        """Bytes of code per language, e.g. {"Python": 120000, "TypeScript": 340000}."""
        return self.get_json(f"/repos/{full_name}/languages")

    def list_closed_pulls(self, full_name: str) -> list[dict]:
        return self.get_json(
            f"/repos/{full_name}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100},
        )

    def list_commits(self, full_name: str, since_iso: str) -> list[dict]:
        try:
            return self.get_json(f"/repos/{full_name}/commits", params={"since": since_iso, "per_page": 100})
        except GitHubError as exc:
            if exc.status == 409:  # empty repository
                return []
            raise

    def download_tarball(self, full_name: str, ref: str = "HEAD") -> bytes:
        """Download a repo archive (redirects to codeload; the token is not sent there)."""
        chunks: list[bytes] = []
        total = 0
        with self._client.stream("GET", f"/repos/{full_name}/tarball/{ref}", timeout=120) as resp:
            self.calls["core"] += 1
            if resp.status_code >= 400:
                resp.read()
                raise GitHubError(resp.status_code, _message(resp))
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > MAX_TARBALL_BYTES:
                    raise GitHubError(413, f"archive larger than {MAX_TARBALL_BYTES} bytes")
                chunks.append(chunk)
        return b"".join(chunks)


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message", resp.text[:200]))
    except ValueError:
        return resp.text[:200]
