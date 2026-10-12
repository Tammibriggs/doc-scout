from conftest import iso

from docscout.apitypes.rest import RestApi
from docscout.classify import classify as _classify

REST = [RestApi()]


def classify(meta, **kwargs):
    return _classify(meta, api_types=REST, **kwargs)


def meta(name, description, topics=(), created_days_ago=400):
    return {"full_name": f"org/{name}", "description": description, "topics": list(topics), "created_at": iso(created_days_ago)}


def test_code_generator_is_tooling(now):
    c = classify(meta("kubb", "Turn your API spec into type-safe code. Generate TypeScript types", ["openapi", "codegen", "generator"]), now=now)
    assert c.project_type == "api_tooling"
    assert c.api_confidence < 0.4


def test_sdk_is_library(now):
    c = classify(meta("apify-client-python", "Apify API client for Python", ["sdk", "client"]), now=now)
    assert c.project_type == "library"


def test_self_hosted_app_serves_api(now):
    c = classify(meta("solidping", "Distributed, self-hostable uptime monitoring dashboard", ["self-hosted", "monitoring"]), now=now)
    assert c.project_type == "serves_api"
    assert c.api_confidence >= 0.5


def test_promotional_new_repo_is_spam(now):
    m = meta("stars-api", "Free Telegram Stars API 2026: 0% fee, best price", ["telegram"], created_days_ago=20)
    assert classify(m, now=now).project_type == "spam"


def test_old_repo_with_alternative_wording_is_not_spam(now):
    m = meta("weave", "Open-source, self-hosted alternative to Airtable", ["self-hosted"], created_days_ago=20)
    assert classify(m, now=now).project_type == "serves_api"


def test_keyword_stuffing_is_spam(now):
    m = meta("x", "thing", [f"topic{i}" for i in range(20)])
    assert classify(m, now=now).project_type == "spam"


def test_curated_prior_lifts_plain_description(now):
    m = meta("notes", "Note taking without the hassle")
    assert classify(m, now=now).api_confidence < classify(m, now=now, prior=0.2).api_confidence
    assert classify(m, now=now, prior=0.2).project_type == "serves_api"


def test_tree_and_readme_evidence_raise_confidence(now):
    m = meta("notes", "Note taking without the hassle")
    tree = [{"path": "docker-compose.yml", "type": "blob", "size": 10}, {"path": "api/openapi.yaml", "type": "blob", "size": 900}]
    readme = "## REST API\nGET /api/notes\nPOST /api/notes\nDELETE /api/notes/{id}\n"
    stage1 = classify(m, now=now)
    stage2 = classify(m, now=now, tree=tree, readme=readme)
    assert stage2.api_confidence > stage1.api_confidence
    assert stage2.project_type == "serves_api"
    assert any("endpoints" in r for r in stage2.reasons)


def test_reports_best_api_type_and_per_type_confidence(now):
    c = classify(meta("notes", "Self-hosted notes app with a REST API"), now=now)
    assert c.api_type == "rest"
    assert c.per_type == {"rest": c.api_confidence}
    assert "describes a REST/HTTP API" in c.reasons


def test_maintainer_help_request_about_rest_docs_is_evidence(now):
    m = meta("notes", "Note taking without the hassle")
    without = classify(m, now=now)
    with_issue = classify(m, now=now, issues=[{"title": "Document the OpenAPI spec for /notes"}])
    assert with_issue.api_confidence > without.api_confidence
    assert "maintainers asked for REST API docs help" in with_issue.reasons
    # A generic "document the API" issue doesn't say which API type: the LLM decides that.
    generic = classify(m, now=now, issues=[{"title": "Improve the API docs"}])
    assert generic.api_confidence == without.api_confidence
