import httpx
import pytest

from docscout.github import AuthError, GitHub, RateLimited


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0
        self.slept: list[float] = []

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def client(handler, token="tok", clock=None, max_wait=900):
    clock = clock or FakeClock()
    return GitHub(token, transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.time, max_wait=max_wait), clock


def test_secondary_rate_limit_waits_for_retry_after_then_succeeds():
    responses = iter(
        [
            httpx.Response(403, headers={"Retry-After": "30"}, json={"message": "secondary rate limit"}),
            httpx.Response(200, json={"full_name": "a/b"}),
        ]
    )
    gh, clock = client(lambda req: next(responses))
    assert gh.get_repo("a/b")["full_name"] == "a/b"
    assert 30 in clock.slept


def test_exhausted_quota_waits_until_reset():
    clock = FakeClock()
    responses = iter(
        [
            httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(clock.t) + 120)}, json={}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    gh, _ = client(lambda req: next(responses), clock=clock)
    gh.get_repo("a/b")
    assert clock.slept and 119 <= clock.slept[0] <= 122


def test_long_wait_raises_instead_of_blocking():
    clock = FakeClock()
    gh, _ = client(
        lambda req: httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(clock.t) + 3600)}, json={}),
        clock=clock,
        max_wait=900,
    )
    with pytest.raises(RateLimited):
        gh.get_repo("a/b")


def test_401_raises_auth_error():
    gh, _ = client(lambda req: httpx.Response(401, json={"message": "Bad credentials"}))
    with pytest.raises(AuthError):
        gh.get_repo("a/b")


def test_search_calls_are_paced():
    gh, clock = client(lambda req: httpx.Response(200, json={"total_count": 0, "items": []}))
    gh.search_repos("x")
    gh.search_repos("y")
    assert clock.slept and clock.slept[-1] == pytest.approx(2.1, abs=0.01)
    assert gh.calls["search"] == 2


def test_token_is_not_sent_to_codeload_on_tarball_redirect():
    seen_auth = {}

    def handler(req):
        seen_auth[req.url.host] = req.headers.get("Authorization")
        if req.url.host == "api.github.com":
            return httpx.Response(302, headers={"Location": "https://codeload.github.com/a/b/legacy.tar.gz/HEAD"})
        return httpx.Response(200, content=b"archive")

    gh, _ = client(handler)
    assert gh.download_tarball("a/b") == b"archive"
    assert seen_auth["api.github.com"] == "Bearer tok"
    assert seen_auth["codeload.github.com"] is None


def test_code_search_requires_token():
    gh, _ = client(lambda req: httpx.Response(200, json={}), token=None)
    with pytest.raises(AuthError):
        gh.search_code("filename:openapi.yaml")


def test_short_lived_404_after_repo_fetch_is_retried_once():
    # Seen live: /pulls returned 404 once for a repo that had just been fetched fine.
    responses = iter([httpx.Response(404, json={"message": "Not Found"}), httpx.Response(200, json=[{"number": 1}])])
    gh, clock = client(lambda req: next(responses), token=None)  # without a token, PR lists come from REST
    assert gh.list_closed_pulls("a/b") == [{"number": 1}]
    assert 2 in clock.slept


def test_lasting_404_still_raises_and_plain_lookups_are_not_retried():
    from docscout.github import NotFound

    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(404, json={"message": "Not Found"})

    gh, _ = client(handler, token=None)
    with pytest.raises(NotFound):
        gh.list_commits("a/b", "2026-01-01T00:00:00Z")
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(NotFound):
        gh.get_repo("a/gone")
    assert len(calls) == 1


# ---------------------------------------------------------------------- GraphQL (with a token)


def graphql_handler(answers, seen):
    import json

    def handler(req):
        assert req.url.path == "/graphql" and req.method == "POST"
        body = json.loads(req.content)
        seen.append(body["variables"])
        return next(answers)

    return handler


def test_pr_and_commit_lists_use_small_graphql_answers_in_the_rest_shape():
    pr = {"number": 7, "title": "docs: endpoints", "headRefName": "docs-api", "createdAt": "2026-10-01T00:00:00Z",
          "closedAt": "2026-10-02T00:00:00Z", "mergedAt": "2026-10-02T00:00:00Z", "authorAssociation": "CONTRIBUTOR",
          "author": {"login": "ana", "__typename": "User"}}  # fmt: skip
    bot_pr = dict(pr, number=8, author={"login": "dependabot", "__typename": "Bot"})
    commit = {"oid": "abc123", "author": {"email": "ana@example.com", "user": {"login": "ana"}}}
    unlinked = {"oid": "def456", "author": {"email": "x@example.com", "user": None}}
    answers = iter([
        httpx.Response(200, json={"data": {"repository": {"pullRequests": {"nodes": [pr, bot_pr]}}}}),
        httpx.Response(200, json={"data": {"repository": {"defaultBranchRef": {"target": {"history": {"nodes": [commit, unlinked]}}}}}}),
        httpx.Response(200, json={"data": {"repository": {"defaultBranchRef": None}}}),
    ])  # fmt: skip
    seen = []
    gh, _ = client(graphql_handler(answers, seen))
    pulls = gh.list_closed_pulls("org/app")
    assert pulls[0] == {"number": 7, "title": "docs: endpoints", "head": {"ref": "docs-api"}, "user": {"login": "ana", "type": "User"},
                        "author_association": "CONTRIBUTOR", "created_at": "2026-10-01T00:00:00Z",
                        "closed_at": "2026-10-02T00:00:00Z", "merged_at": "2026-10-02T00:00:00Z"}  # fmt: skip
    assert pulls[1]["user"]["type"] == "Bot"
    assert seen[0] == {"owner": "org", "name": "app", "states": ["CLOSED", "MERGED"], "after": None}
    commits = gh.list_commits("org/app", "2026-07-01T00:00:00Z")
    assert commits == [
        {"sha": "abc123", "author": {"login": "ana"}, "commit": {"author": {"email": "ana@example.com"}}},
        {"sha": "def456", "author": None, "commit": {"author": {"email": "x@example.com"}}},
    ]
    assert gh.list_commits("org/empty", "2026-07-01T00:00:00Z") == []  # empty repository
    assert gh.calls["graphql"] == 3


def test_graphql_not_found_is_retried_once_and_rate_limits_wait():
    from docscout.github import NotFound

    clock = FakeClock()
    missing = httpx.Response(200, json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}]})
    limited = httpx.Response(200, headers={"X-RateLimit-Reset": str(int(clock.t) + 120)},
                             json={"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]})  # fmt: skip
    found = httpx.Response(200, json={"data": {"repository": {"pullRequests": {"nodes": []}}}})
    gh, _ = client(graphql_handler(iter([missing, limited, found]), []), clock=clock)
    assert gh.list_open_pulls("org/app") == []
    assert clock.slept[0] == 2 and 119 <= clock.slept[1] <= 122

    gh, _ = client(graphql_handler(iter([missing, missing]), []))
    with pytest.raises(NotFound):
        gh.list_closed_pulls("org/gone")


def test_a_second_page_of_prs_only_when_the_first_is_all_recent():
    clock = FakeClock()  # 1970-01-12: PRs updated in 1970 are within 180 days
    recent = {"number": 1, "updatedAt": "1970-01-10T00:00:00Z", "author": None}
    old = {"number": 2, "updatedAt": "1960-01-01T00:00:00Z", "author": None}

    def page(nodes, more):
        return httpx.Response(200, json={"data": {"repository": {"pullRequests": {
            "pageInfo": {"hasNextPage": more, "endCursor": "c1"}, "nodes": nodes}}}})  # fmt: skip

    seen = []
    gh, _ = client(graphql_handler(iter([page([recent], True), page([old], True)]), seen), clock=clock)
    assert [p["number"] for p in gh.list_closed_pulls("org/app")] == [1, 2]
    assert [v["after"] for v in seen] == [None, "c1"]  # stops after 2 pages even if there are more

    seen.clear()
    gh, _ = client(graphql_handler(iter([page([old], True)]), seen), clock=clock)
    assert [p["number"] for p in gh.list_closed_pulls("org/app")] == [2] and len(seen) == 1


def test_issue_search_and_owner_repos_come_from_graphql_with_only_the_fields_used():
    from docscout.sources import help_requested

    issue = {"number": 12, "title": "Document the API", "url": "https://github.com/org/app/issues/12", "authorAssociation": "NONE",
             "author": {"login": "ana", "__typename": "User"}, "labels": {"nodes": [{"name": "docs"}]},
             "repository": {"nameWithOwner": "org/app"}}  # fmt: skip
    answers = iter([
        httpx.Response(200, json={"data": {"search": {"issueCount": 1, "nodes": [issue, {}]}}}),  # {} = a pull request
        httpx.Response(200, json={"data": {"repositoryOwner": {"repositories": {"nodes": [
            {"nameWithOwner": "org/app-docs", "isArchived": False}, {"nameWithOwner": "org/old", "isArchived": True}]}}}}),
    ])  # fmt: skip
    seen = []
    gh, _ = client(graphql_handler(answers, seen))
    found = list(help_requested.fetch(gh, ["is:issue label:docs api in:title"], label_denylist=[], title_denylist=[]))
    assert [(c.full_name, c.issues[0]["html_url"], c.issues[0]["labels"]) for c in found] == [
        ("org/app", "https://github.com/org/app/issues/12", ["docs"])
    ]
    assert seen[0] == {"q": "is:issue label:docs api in:title sort:updated-desc", "first": 50}
    assert gh.list_owner_repos("org") == [{"full_name": "org/app-docs", "archived": False}, {"full_name": "org/old", "archived": True}]
