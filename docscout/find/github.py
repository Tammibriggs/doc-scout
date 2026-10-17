"""Small GitHub REST client that respects GitHub's rate limits.

GitHub has separate budgets per resource: ``core`` (5000/h with a token), ``search``
(30/min with a token, 10/min without), ``code_search`` (10/min, token required) and
``graphql`` (5000 points/h, token required). Searches are paced proactively; exhausted
budgets wait for the reset time from the response headers, or raise
:class:`RateLimited` when the wait would be too long.

Pull request and commit lists use GraphQL when there's a token: the REST lists return
about 19 KB per pull request (1.5-2 MB per repo, 35-65 s on a slow connection), while
GraphQL returns only the fields DocScout reads, about 100 times less.
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

PR_WINDOW_DAYS = 180  # the health check counts pull requests closed in this window
# Pages of 50: measured live, asking for 100 at once took 12-28 s, 50 usually 1-5 s.
_PULLS_QUERY = """
query($owner: String!, $name: String!, $states: [PullRequestState!], $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: $states, first: 50, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title headRefName createdAt updatedAt closedAt mergedAt authorAssociation author { login __typename } }
    }
  }
}"""

# Open PRs with what the model needs to judge whether one already covers a docs gap: the
# description and changed files as well as the title (17 Oct: titles alone flagged a licence fix).
_OPEN_PULLS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: [OPEN], first: 30, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title headRefName createdAt updatedAt isDraft bodyText author { login __typename } files(first: 10) { nodes { path } } }
    }
  }
}"""

# Issue search with only the fields the help_requested source reads: REST search results
# carry each issue's full text (230-630 KB per search, up to 2.5 minutes on a slow link).
_ISSUES_QUERY = """
query($q: String!, $first: Int!) {
  search(query: $q, type: ISSUE, first: $first) {
    issueCount
    nodes {
      ... on Issue {
        number title url authorAssociation
        author { login __typename }
        labels(first: 20) { nodes { name } }
        repository { nameWithOwner }
      }
    }
  }
}"""

_OWNER_REPOS_QUERY = """
query($login: String!) {
  repositoryOwner(login: $login) {
    repositories(first: 100, privacy: PUBLIC, orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { nameWithOwner isArchived }
    }
  }
}"""

_COMMITS_QUERY = """
query($owner: String!, $name: String!, $since: GitTimestamp!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target { ... on Commit { history(first: 100, since: $since) { nodes { oid author { email user { login } } } } } }
    }
  }
}"""

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
        retry_not_found: bool = False,
        json: Any = None,
    ) -> httpx.Response:
        """Send a request, waiting out rate limits and retrying server errors.

        ``retry_not_found`` retries one 404, for requests about a repo that was just
        fetched successfully: GitHub occasionally returns a short-lived 404 there.
        """
        not_found_retried = False
        for attempt in range(5):
            self._wait_for_pace(resource)
            try:
                resp = self._client.request(method, path, params=params, headers=headers, json=json)
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
                if retry_not_found and not not_found_retried:
                    not_found_retried = True
                    log.info("GitHub returned 404 for %s; retrying once", path)
                    self._sleep(2)
                    continue
                raise NotFound(404, _message(resp))
            if resp.status_code >= 400:
                raise GitHubError(resp.status_code, _message(resp))
            return resp
        raise GitHubError(resp.status_code, "gave up after repeated failures")

    def get_json(
        self, path: str, *, params: dict[str, Any] | None = None, resource: str = "core", retry_not_found: bool = False
    ) -> Any:
        return self.request("GET", path, params=params, resource=resource, retry_not_found=retry_not_found).json()

    # ------------------------------------------------------------------ endpoints

    def graphql(self, query: str, variables: dict[str, Any], *, retry_not_found: bool = False) -> dict[str, Any]:
        """Run a GraphQL query (needs a token) and return its ``data``."""
        not_found_retried = False
        for _ in range(4):
            resp = self.request("POST", "/graphql", json={"query": query, "variables": variables}, resource="graphql")
            body = resp.json()
            errors = body.get("errors") or []
            if not errors:
                return body.get("data") or {}
            kinds = {e.get("type") for e in errors}
            message = "; ".join(str(e.get("message", "")) for e in errors)[:300]
            if "RATE_LIMITED" in kinds:
                reset = float(resp.headers.get("X-RateLimit-Reset", "0"))
                wait = max(60.0, reset - self._clock() + 1)
                if wait > self._max_wait:
                    raise RateLimited("graphql", wait)
                log.info("GitHub graphql rate limit reached; waiting %ds", int(wait))
                self._sleep(wait)
                continue
            if "NOT_FOUND" in kinds:
                if retry_not_found and not not_found_retried:
                    not_found_retried = True
                    self._sleep(2)
                    continue
                raise NotFound(404, message)
            raise GitHubError(400, f"GraphQL: {message}")
        raise GitHubError(400, "GraphQL: gave up after repeated failures")

    def _pulls(self, full_name: str, states: list[str], *, max_pages: int, updated_since: str | None = None) -> list[dict]:
        """Newest-updated PRs first; a further page only while they're newer than ``updated_since``."""
        owner, name = full_name.split("/", 1)
        pulls: list[dict] = []
        after = None
        for _ in range(max_pages):
            variables = {"owner": owner, "name": name, "states": states, "after": after}
            data = self.graphql(_PULLS_QUERY, variables, retry_not_found=True)
            page = ((data.get("repository") or {}).get("pullRequests")) or {}
            nodes = [node for node in page.get("nodes") or [] if node]
            pulls += [_pull_as_rest(node) for node in nodes]
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage") or not nodes:
                break
            if updated_since and (nodes[-1].get("updatedAt") or "") < updated_since:
                break
            after = info.get("endCursor")
        return pulls

    def ping(self, timeout: float = 10.0) -> int:
        """One quick request without retries, for checking the connection and the token.

        Returns the HTTP status (401 means the token was rejected). Raises
        ``httpx.TransportError`` when GitHub can't be reached. ``/rate_limit`` is free.
        """
        return self._client.get("/rate_limit", timeout=timeout).status_code

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
        """Issues matching a search, most recently updated first (fields as in the REST API).

        With a token, the first page comes from GraphQL, with at most 50 issues."""
        if self.has_token and page == 1:
            data = self.graphql(_ISSUES_QUERY, {"q": f"{query} sort:updated-desc", "first": min(per_page, 50)})
            result = data.get("search") or {}
            nodes = [n for n in result.get("nodes") or [] if n and n.get("repository")]
            return int(result.get("issueCount") or 0), [_issue_as_rest(n) for n in nodes]
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
        data = self.get_json(f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"}, retry_not_found=True)
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
        return self.get_json(f"/repos/{full_name}/languages", retry_not_found=True)

    def list_owner_repos(self, owner: str) -> list[dict]:
        """The owner's most recently pushed public repos (works for users and organizations).
        With a token only ``full_name`` and ``archived`` are filled in."""
        if self.has_token:
            data = self.graphql(_OWNER_REPOS_QUERY, {"login": owner})
            nodes = (((data.get("repositoryOwner") or {}).get("repositories")) or {}).get("nodes") or []
            return [{"full_name": n.get("nameWithOwner"), "archived": bool(n.get("isArchived"))} for n in nodes if n]
        return self.get_json(f"/users/{owner}/repos", params={"sort": "pushed", "per_page": 100})

    def get_issue(self, full_name: str, number: int) -> dict[str, Any]:
        return self.get_json(f"/repos/{full_name}/issues/{number}")

    def list_open_pulls(self, full_name: str) -> list[dict]:
        """The 30 most recently updated open PRs, with description and (with a token) changed files."""
        if self.has_token:
            owner, name = full_name.split("/", 1)
            data = self.graphql(_OPEN_PULLS_QUERY, {"owner": owner, "name": name}, retry_not_found=True)
            nodes = (((data.get("repository") or {}).get("pullRequests")) or {}).get("nodes") or []
            return [_open_pull_as_rest(node) for node in nodes if node]
        return self.get_json(f"/repos/{full_name}/pulls", params={"state": "open", "sort": "updated", "direction": "desc", "per_page": 30}, retry_not_found=True)

    def list_issue_comments(self, full_name: str, number: int) -> list[dict]:
        return self.get_json(f"/repos/{full_name}/issues/{number}/comments", params={"per_page": 100})

    def list_closed_pulls(self, full_name: str) -> list[dict]:
        """Recently updated closed and merged PRs, newest first (fields as in the REST API)."""
        if self.has_token:
            since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock() - PR_WINDOW_DAYS * 86400))
            return self._pulls(full_name, ["CLOSED", "MERGED"], max_pages=2, updated_since=since)
        return self.get_json(
            f"/repos/{full_name}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100},
            retry_not_found=True,
        )

    def list_commits(self, full_name: str, since_iso: str) -> list[dict]:
        """Commits on the default branch since a time, newest first (fields as in the REST API)."""
        if self.has_token:
            owner, name = full_name.split("/", 1)
            data = self.graphql(_COMMITS_QUERY, {"owner": owner, "name": name, "since": since_iso}, retry_not_found=True)
            branch = (data.get("repository") or {}).get("defaultBranchRef")
            if not branch:  # empty repository
                return []
            nodes = ((branch.get("target") or {}).get("history") or {}).get("nodes") or []
            return [_commit_as_rest(node) for node in nodes if node]
        try:
            return self.get_json(f"/repos/{full_name}/commits", params={"since": since_iso, "per_page": 100}, retry_not_found=True)
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


def _pull_as_rest(node: dict[str, Any]) -> dict[str, Any]:
    """A GraphQL pull request in the REST shape the health checks read."""
    author = node.get("author")
    return {
        "number": node.get("number"),
        "title": node.get("title") or "",
        "head": {"ref": node.get("headRefName") or ""},
        "user": {"login": author.get("login"), "type": author.get("__typename")} if author else None,
        "author_association": node.get("authorAssociation"),
        "created_at": node.get("createdAt"),
        "closed_at": node.get("closedAt"),
        "merged_at": node.get("mergedAt"),
    }


def _open_pull_as_rest(node: dict[str, Any]) -> dict[str, Any]:
    """An open GraphQL pull request in the REST shape, plus ``files`` (changed paths)."""
    files = ((node.get("files") or {}).get("nodes")) or []
    return {
        **_pull_as_rest(node),
        "updated_at": node.get("updatedAt"),
        "draft": bool(node.get("isDraft")),
        "body": node.get("bodyText") or "",
        "files": [f.get("path") for f in files if f and f.get("path")],
    }


def _commit_as_rest(node: dict[str, Any]) -> dict[str, Any]:
    """A GraphQL commit in the REST shape: ``author`` is None when no GitHub account matches."""
    git_author = node.get("author") or {}
    user = git_author.get("user")
    return {
        "sha": node.get("oid"),
        "author": {"login": user.get("login")} if user else None,
        "commit": {"author": {"email": git_author.get("email")}},
    }


def _issue_as_rest(node: dict[str, Any]) -> dict[str, Any]:
    """A GraphQL search result in the REST shape the help_requested source reads."""
    author = node.get("author")
    return {
        "number": node.get("number"),
        "title": node.get("title") or "",
        "html_url": node.get("url"),
        "repository_url": f"{API_URL}/repos/{node['repository']['nameWithOwner']}",
        "user": {"login": author.get("login"), "type": author.get("__typename")} if author else None,
        "author_association": node.get("authorAssociation"),
        "labels": [{"name": label.get("name", "")} for label in ((node.get("labels") or {}).get("nodes") or []) if label],
    }
