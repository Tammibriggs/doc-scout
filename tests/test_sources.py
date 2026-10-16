import io
import tarfile
from datetime import date

from docscout.sources import github_full_name
from docscout.sources import awesome_selfhosted, code_search, help_requested, repo_search


def make_tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_github_full_name():
    assert github_full_name("https://github.com/go-gitea/gitea") == "go-gitea/gitea"
    assert github_full_name("https://github.com/owner/repo.git/") == "owner/repo"
    assert github_full_name("https://github.com/owner/repo/tree/main/sub") == "owner/repo"
    assert github_full_name("https://gitlab.com/owner/repo") is None
    assert github_full_name(None) is None


def test_seed_archive_parsing_skips_unsafe_and_irrelevant_entries():
    data = make_tarball(
        {
            "root/software/gitea.yml": "name: Gitea\ndescription: Git service\nsource_code_url: https://github.com/go-gitea/gitea\nstargazers_count: 5\n",
            "root/software/old.yml": "name: Old\nsource_code_url: https://github.com/a/old\narchived: true\n",
            "root/software/gl.yml": "name: GL\nsource_code_url: https://gitlab.com/a/b\n",
            "root/software/bomb.yml": "a: &a [x, x]\nb: [*a, *a]\nsource_code_url: https://github.com/a/bomb\n",
            "root/tags/other.yml": "source_code_url: https://github.com/a/tag\n",
            "../escape/software/x.yml": "source_code_url: https://github.com/a/escape\n",
        }
    )
    found = {c.full_name: c for c in awesome_selfhosted.parse_archive(data)}
    assert set(found) == {"go-gitea/gitea"}
    assert found["go-gitea/gitea"].prior == awesome_selfhosted.PRIOR
    assert found["go-gitea/gitea"].meta["description"] == "Git service"


def test_repo_search_slices(now):
    slices = repo_search.all_slices(["topic:openapi"], [[10, 50], [5000, None]])
    assert [s.key for s in slices] == ["topic:openapi|10..50|", "topic:openapi|5000..*|"]
    q = slices[0].search_query(date(2026, 8, 13))
    assert q == "topic:openapi stars:10..50 archived:false fork:false pushed:>2026-08-13"
    assert "stars:5000..*" in slices[1].search_query(date(2026, 8, 13))
    with_lang = repo_search.all_slices(["topic:openapi"], [[10, 50]], "language:python language:go")
    assert with_lang[0].search_query(date(2026, 8, 13)).endswith("pushed:>2026-08-13 language:python language:go")


def test_code_search_queries():
    assert code_search.queries(["openapi.yaml"], ["<5000"]) == ["filename:openapi.yaml size:<5000"]


def test_issue_queries_use_comma_labels_and_one_keyword_each():
    qs = help_requested.queries(["documentation,docs"], ["api", "openapi"], date(2026, 10, 1))
    assert len(qs) == 2
    assert "label:documentation,docs api in:title" in qs[0]
    assert " OR " not in qs[0]
    assert "no:assignee" in qs[0] and "-linked:pr" in qs[0]


def issue(assoc="OWNER", labels=(), title="Document the API", login="bob", user_type="User"):
    return {
        "user": {"login": login, "type": user_type},
        "author_association": assoc,
        "labels": [{"name": n} for n in labels],
        "title": title,
    }


DENY = {"label_denylist": ["bounty", "tier:", "points"], "title_denylist": ["dependency dashboard"]}


def test_issue_filter():
    # Owner tracking their own plan: no outreach label -> doesn't count.
    assert not help_requested.issue_counts(issue("OWNER", ["documentation"]), **DENY)
    # Owner explicitly asking for help -> counts.
    assert help_requested.issue_counts(issue("OWNER", ["documentation", "help-wanted"]), **DENY)
    assert help_requested.issue_counts(issue("MEMBER", ["Good First Issue"]), **DENY)
    # Outsider reporting missing docs -> counts.
    assert help_requested.issue_counts(issue("NONE", ["docs"]), **DENY)
    # Bots, dashboards and bounty farms never count.
    assert not help_requested.issue_counts(issue("NONE", ["docs"], login="renovate[bot]", user_type="Bot"), **DENY)
    assert not help_requested.issue_counts(issue("NONE", ["docs"], title="Dependency Dashboard"), **DENY)
    assert not help_requested.issue_counts(issue("NONE", ["help wanted", "tier:trivial"]), **DENY)


def test_outreach_issues_count_only_when_they_are_about_docs():
    # Seen 15 Oct: a bug and a feature request found by "help wanted" or "good first issue" plus "api".
    bug = "OpenAPI DecimalValue rejects canonical negative fractions accepted by the runtime"
    feature = "Accept Claude Platform OpenTelemetry export (Claude Managed Agents + Messages API)"
    assert not help_requested.issue_counts(issue("MEMBER", ["good first issue"], title=bug), **DENY)
    assert not help_requested.issue_counts(issue("OWNER", ["help wanted", "docker"], title=feature), **DENY)
    assert help_requested.issue_counts(issue("OWNER", ["help wanted"], title="Document webhook payloads"), **DENY)
    assert help_requested.issue_counts(issue("OWNER", ["help wanted"], title="API docs: OpenAPI omits response schemas"), **DENY)
    # A docs label says it's about docs, whatever the title.
    assert help_requested.issue_counts(issue("OWNER", ["help wanted", "type: docs"], title=bug), **DENY)


# ---------------------------------------------------------------------- when the curated list goes away or stale


class SeedGitHub:
    def __init__(self, archive=None, error=None, info=None):
        self.archive, self.error, self.info = archive, error, info or {"pushed_at": "2026-10-11T00:00:00Z", "archived": False}

    def get_repo(self, name):
        if self.error:
            raise self.error
        return self.info

    def download_tarball(self, name):
        return self.archive


GITEA = {"root/software/gitea.yml": "name: Gitea\nsource_code_url: https://github.com/go-gitea/gitea\n"}


def test_curated_list_falls_back_to_the_last_copy_and_otherwise_steps_aside(tmp_path):
    import pytest

    from docscout.github import NotFound
    from docscout.sources import SourceUnavailable

    cache = tmp_path / "seed.json"
    fresh = awesome_selfhosted.load_seed(SeedGitHub(make_tarball(GITEA)), cache, max_age_days=7)
    assert [c.full_name for c in fresh] == ["go-gitea/gitea"]

    # Cache too old and the list is gone: the old copy is used.
    gone = SeedGitHub(error=NotFound(404, "Not Found"))
    assert [c.full_name for c in awesome_selfhosted.load_seed(gone, cache, max_age_days=0)] == ["go-gitea/gitea"]

    # No copy at all: the source steps aside instead of failing the run.
    with pytest.raises(SourceUnavailable, match="couldn't download the curated list"):
        awesome_selfhosted.load_seed(gone, tmp_path / "none.json", max_age_days=7)


def test_curated_list_staleness_is_reported(tmp_path, now):
    cache = tmp_path / "seed.json"
    awesome_selfhosted.load_seed(SeedGitHub(make_tarball(GITEA)), cache, max_age_days=7)
    assert awesome_selfhosted.staleness_note(cache, now) is None

    old = SeedGitHub(make_tarball(GITEA), info={"pushed_at": "2025-12-01T00:00:00Z", "archived": False})
    awesome_selfhosted.load_seed(old, cache, max_age_days=0)
    assert "hasn't been updated since 01 Dec 2025" in awesome_selfhosted.staleness_note(cache, now)

    archived = SeedGitHub(make_tarball(GITEA), info={"pushed_at": "2026-10-01T00:00:00Z", "archived": True})
    awesome_selfhosted.load_seed(archived, cache, max_age_days=0)
    assert "is archived" in awesome_selfhosted.staleness_note(cache, now)


def test_cache_from_an_older_version_still_loads(tmp_path):
    import json

    cache = tmp_path / "seed.json"
    cache.write_text(json.dumps([{"full_name": "a/b", "meta": {"full_name": "a/b"}}]))
    assert [c.full_name for c in awesome_selfhosted.load_seed(SeedGitHub(), cache, max_age_days=7)] == ["a/b"]
