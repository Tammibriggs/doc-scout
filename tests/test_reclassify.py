from pathlib import Path

from conftest import iso

from docscout.apitypes.rest import RestApi
from docscout.discover import LABELS
from docscout.evaluate import evaluate_rows, read_rows
from docscout.reclassify import _issue_numbers, reclassify

FIXTURE = Path(__file__).parent / "fixtures" / "labeled_repos.csv"


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def get_repo(self, name):
        self.calls.append(("repo", name))
        return {"full_name": name, "description": "Self-hosted tracker with a REST API", "topics": [], "created_at": iso(900),
                "stargazers_count": 300, "default_branch": "main"}  # fmt: skip

    def get_tree(self, name, ref):
        self.calls.append(("tree", name))
        return [{"path": "docker-compose.yml", "type": "blob", "size": 9}, {"path": "src/deep/file.py", "type": "blob", "size": 9}], False

    def get_readme(self, name):
        return "GET /api/a\nGET /api/b\nGET /api/c"

    def get_issue(self, name, number):
        self.calls.append(("issue", number))
        return {"title": "Document the OpenAPI spec"}


def test_reclassify_caches_inputs_and_reports_changes(tmp_path, now):
    rows = [{"label": "serves_api", "full_name": "org/app", "source": "repo_search", "predicted_type": "spam", "api_confidence": "0.05",
             "issues": "see https://github.com/org/app/issues/12"}]  # fmt: skip
    gh = FakeGitHub()
    cache = tmp_path / "cache.json"
    new_rows, changed, missing = reclassify(rows, gh, cache, now, [RestApi()])
    assert new_rows[0]["predicted_type"] == "serves_api" and missing == []
    assert [(c.before, c.after) for c in changed] == [("spam", "serves_api")]
    assert ("issue", 12) in gh.calls
    calls = len(gh.calls)
    reclassify(rows, gh, cache, now, [RestApi()])
    assert len(gh.calls) == calls  # second run: everything from the cache
    assert "src/deep/file.py" not in cache.read_text()  # only files the classifier reads are cached


def test_issue_links_are_found_even_in_shifted_columns():
    row = {"label": "serves_api", "full_name": "org/app", "note": "https://github.com/org/app/issues/7", None: ["https://github.com/org/app/issues/9"]}
    assert _issue_numbers(row, "org/app") == [7, 9]


def test_labeled_fixture_is_well_formed():
    rows = read_rows(FIXTURE)
    assert len(rows) == 58
    assert {r["label"] for r in rows} <= set(LABELS)
    assert {r["source"] for r in rows} == {"awesome_selfhosted", "help_requested", "repo_search"}
    assert evaluate_rows(rows).overall.precision is not None
