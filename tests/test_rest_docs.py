from pathlib import Path

from docscout.analyze.elsewhere import docs_elsewhere, doc_links, sibling_repos
from docscout.apitypes.base import DocsContext
from docscout.apitypes.rest import RestApi
from docscout.apitypes.rest_prose import analyze_docs, analyze_text
from docscout.github import NotFound

FIXTURES = Path(__file__).parent / "fixtures"


def readme(name):
    return (FIXTURES / "readmes" / name).read_text()


def blob(path, size=1000):
    return {"path": path, "type": "blob", "size": size}


class FakeGitHub:
    def __init__(self, files=None, owner_repos=()):
        self.files = files or {}
        self.owner_repos = list(owner_repos)
        self.fetched = []

    def get_file(self, full_name, path, ref=None, max_bytes=None):
        self.fetched.append(path)
        if path not in self.files:
            raise NotFound(404, "Not Found")
        return self.files[path]

    def list_owner_repos(self, owner):
        return self.owner_repos


def ctx(gh, tree=(), text="", repo=None, confidence=0.6):
    return DocsContext(gh=gh, full_name="org/app", repo=repo or {}, tree=list(tree), readme=text, head_sha="abc123", type_confidence=confidence)


# ---------------------------------------------------------------------- prose


def test_thin_readme_endpoints_are_missing_almost_everything():
    endpoints = analyze_text(readme("thin.md"))
    assert [e.label for e in endpoints] == ["GET /api/bookmarks", "POST /api/bookmarks", "DELETE /api/bookmarks/{id}"]
    assert all(e.completeness <= 0.25 for e in endpoints)
    assert all("request example" in e.missing and "response example" in e.missing for e in endpoints)


def test_thorough_readme_endpoints_are_complete():
    endpoints = analyze_text(readme("thorough.md"))
    assert [e.label for e in endpoints] == ["GET /api/checks", "POST /api/checks"]
    for e in endpoints:
        assert e.missing == [], (e.label, e.missing)
        assert e.completeness == 1.0


def test_table_rows_get_descriptions_from_their_cells_but_no_examples():
    endpoints = {e.label: e for e in analyze_text(readme("table.md"))}
    assert "description" not in endpoints["GET /api/notes"].missing
    assert "description" in endpoints["POST /api/notes"].missing
    assert all("request example" in e.missing for e in endpoints.values())


def test_findings_count_missing_pieces_across_files():
    result = analyze_docs([("README", readme("thin.md")), ("docs/api.md", readme("thorough.md"))])
    assert len(result.endpoints) == 5 and result.source == "README"
    texts = [f.text for f in result.findings()]
    assert "3/5 endpoints have no request example" in texts


# ---------------------------------------------------------------------- elsewhere


def test_docs_elsewhere_signals():
    text = (
        "See the [documentation](https://docs.myapp.example/api) and ![build](https://img.shields.io/x.svg) "
        "[code](https://github.com/org/app) and [framework docs](https://framework.org/docs)"
    )
    assert doc_links(text, "org/myapp") == ["docs.myapp.example"]
    owner = [{"full_name": "org/app"}, {"full_name": "org/app-docs"}, {"full_name": "org/website"}, {"full_name": "org/cli"}]
    assert sibling_repos(owner, "org/app") == ["org/app-docs", "org/website"]
    reasons = docs_elsewhere({"homepage": "https://app.example.com"}, text, owner, "org/myapp")
    assert reasons[0] == "Project website: app.example.com"
    assert "Separate docs repo: org/website" in reasons and "Separate docs repo: org/app-docs" not in reasons  # another project's


def test_docs_signals_must_belong_to_this_project():
    # Seen in the first daily report (13 Oct): another Apache project's site, and Django's own docs.
    apache = [{"full_name": f"apache/project{i}"} for i in range(40)] + [{"full_name": "apache/tvm-site"}, {"full_name": "apache/airflow-site"}]
    assert sibling_repos(apache, "apache/ofbiz-framework") == []
    assert sibling_repos(apache + [{"full_name": "apache/ofbiz-site"}], "apache/ofbiz-framework") == ["apache/ofbiz-site"]
    assert doc_links("Built with [Django](https://docs.djangoproject.com/en/5.0/).", "DjangoCRM/django-crm") == []
    assert doc_links("Read [the docs](https://django-crm-admin.readthedocs.io).", "DjangoCRM/django-crm") == ["django-crm-admin.readthedocs.io"]
    # A generic docs repo counts when the owner is the product, however many repos it has.
    kuzzle = [{"full_name": f"kuzzleio/sdk-{i}"} for i in range(40)] + [{"full_name": "kuzzleio/documentation"}]
    assert sibling_repos(kuzzle, "kuzzleio/kuzzle") == ["kuzzleio/documentation"]
    assert sibling_repos([{"full_name": "MylarComics/mylar3-website"}], "MylarComics/mylar3") == ["MylarComics/mylar3-website"]


def test_internal_design_notes_are_not_api_docs():
    gh = FakeGitHub({"docs/adr-001/step-15-audit/A3-api.md": readme("thin.md").encode()})
    gap = RestApi().analyze(ctx(gh, [blob("docs/adr-001/step-15-audit/A3-api.md")], "# App", confidence=0.9))
    assert gh.fetched == [] and gap.kind == "none"


# ---------------------------------------------------------------------- RestApi.analyze


def test_owned_spec_wins_and_is_fetched_at_the_commit():
    spec = (FIXTURES / "specs" / "bare.yaml").read_bytes()
    gh = FakeGitHub({"api/openapi.yaml": spec})
    gap = RestApi().analyze(ctx(gh, [blob("api/openapi.yaml"), blob("vendor/x/openapi.yaml")], readme("thorough.md")))
    assert gap.kind == "spec" and gap.score == 75 and gap.location == "api/openapi.yaml"
    assert gap.summary == "OpenAPI 3.0.3, 4 operations, hand-written" and gap.effort_units == 4
    assert gh.fetched == ["api/openapi.yaml"]  # the vendored spec is never fetched


def test_generated_spec_suggests_editing_annotations():
    spec = b"# Code generated by swag. DO NOT EDIT\n" + (FIXTURES / "specs" / "bare.yaml").read_bytes()
    gap = RestApi().analyze(ctx(FakeGitHub({"docs/swagger.yaml": spec}), [blob("docs/swagger.yaml")]))
    assert gap.generated and "code annotations" in gap.suggestion


def test_thin_prose_without_spec():
    gap = RestApi().analyze(ctx(FakeGitHub(), [], readme("thin.md")))
    assert gap.kind == "prose" and gap.score >= 75 and gap.effort_units == 3
    assert gap.location is None and gap.check_manually == []


def test_complete_prose_suggests_an_openapi_spec():
    gap = RestApi().analyze(ctx(FakeGitHub(), [], readme("thorough.md")))
    assert gap.kind == "prose" and gap.score == 35 and "OpenAPI spec" in gap.suggestion


def test_api_docs_file_in_the_repo_is_read():
    gh = FakeGitHub({"docs/API.md": readme("thorough.md").encode()})
    gap = RestApi().analyze(ctx(gh, [blob("docs/API.md"), blob("tests/api.md")], "# App"))
    assert gap.kind == "prose" and gap.location == "docs/API.md"
    assert "tests/api.md" not in gh.fetched


def test_signs_of_docs_elsewhere_cap_the_gap():
    text = readme("thin.md") + "\nOpen Swagger UI at /docs once it's running.\n"
    gap = RestApi().analyze(ctx(FakeGitHub(), [], text, repo={"homepage": "https://bookmarks.example.com"}))
    assert gap.kind == "prose" and gap.score == 50
    assert any("Swagger UI" in r for r in gap.check_manually)
    assert "Project website: bookmarks.example.com" in gap.check_manually


def test_no_endpoints_but_docs_elsewhere():
    gap = RestApi().analyze(ctx(FakeGitHub(owner_repos=[{"full_name": "org/docs"}]), [], "# App\nA tracker."))
    assert gap.kind == "elsewhere" and gap.score == 40 and gap.check_manually == ["Separate docs repo: org/docs"]


def test_nothing_found_is_reported_only_when_very_likely_an_api():
    assert RestApi().analyze(ctx(FakeGitHub(), [], "# App", confidence=0.6)) is None
    gap = RestApi().analyze(ctx(FakeGitHub(), [], "# App", confidence=0.85))
    assert gap.kind == "none" and gap.score == 60 and gap.unverified


def test_framework_docs_links_and_docs_hosts_are_not_mistaken_for_project_docs():
    text = (
        "Install via [Laravel docs](https://laravel.com/docs/installation). "
        "Full guide at [our docs](https://docs.2fauth.app/getting-started) and https://docs.2fauth.app."
    )
    assert doc_links(text, "Bubka/2FAuth") == ["docs.2fauth.app"]
    gap = RestApi().analyze(ctx(FakeGitHub(), [], text, confidence=0.9))
    assert not any("Swagger UI" in r for r in gap.check_manually)
    fastapi = RestApi().analyze(ctx(FakeGitHub(), [], "Open http://localhost:8000/docs for the API.", confidence=0.9))
    assert any("Swagger UI" in r for r in fastapi.check_manually)


def test_implementing_a_specification_does_not_make_a_project_a_tool(now):
    from conftest import iso

    from docscout.classify import classify

    meta = {"full_name": "project-zot/zot", "created_at": iso(900), "topics": [],
            "description": "A production-ready vendor-neutral OCI image registry, based on the OCI Distribution Specification"}  # fmt: skip
    c = classify(meta, now=now, api_types=[RestApi()])
    assert c.project_type != "api_tooling" and not any("tool words" in r for r in c.reasons)
