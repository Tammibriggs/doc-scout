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
