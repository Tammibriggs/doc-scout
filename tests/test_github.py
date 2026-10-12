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
    gh, clock = client(lambda req: next(responses))
    assert gh.list_closed_pulls("a/b") == [{"number": 1}]
    assert 2 in clock.slept


def test_lasting_404_still_raises_and_plain_lookups_are_not_retried():
    from docscout.github import NotFound

    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(404, json={"message": "Not Found"})

    gh, _ = client(handler)
    with pytest.raises(NotFound):
        gh.list_commits("a/b", "2026-01-01T00:00:00Z")
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(NotFound):
        gh.get_repo("a/gone")
    assert len(calls) == 1
