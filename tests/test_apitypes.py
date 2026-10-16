import random
import re
from datetime import date

import pytest
from conftest import iso

from docscout.analyze import apitypes
from docscout.analyze.apitypes import REGISTRY, ApiType, ConfigError, enabled_types
from docscout.analyze.apitypes.rest import RestApi
from docscout.find.classify import classify
from docscout.find.discover import source_candidates
from docscout.find.evidence import Evidence, Signals


class FakeGraphQL(ApiType):
    """A minimal second API type, to prove new types plug in without touching the core."""

    key = "graphql"
    label = "GraphQL"
    llm_style = "graphql"
    definition_pattern = re.compile(r"\.graphqls?$")

    def evidence(self, signals: Signals) -> Evidence:
        ev = Evidence()
        if "graphql" in signals.tokens:
            ev.add(0.2, "mentions GraphQL")
        if signals.tree is not None and self.find_definitions(signals.tree):
            ev.add(0.1, "owns a GraphQL schema")
        return ev


GRAPHQL_SETTINGS = {
    "repo_queries": ["topic:graphql"],
    "definition_filenames": ["schema.graphql"],
    "issue_keywords": ["graphql", "schema"],
}


@pytest.fixture
def with_graphql(monkeypatch):
    monkeypatch.setitem(REGISTRY, "graphql", FakeGraphQL)
    return enabled_types({"enabled": ["rest", "graphql"], "rest": {"repo_queries": ["topic:openapi"], "issue_keywords": ["openapi"]}, "graphql": GRAPHQL_SETTINGS})


def test_default_config_enables_rest_only(cfg):
    types = enabled_types(cfg["api_types"])
    assert [t.key for t in types] == ["rest"]
    assert "topic:openapi" in types[0].repo_queries
    assert types[0].definition_filenames == ["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"]


def test_config_errors_are_clear():
    with pytest.raises(ConfigError, match="at least one"):
        enabled_types({"enabled": []})
    with pytest.raises(ConfigError, match="unknown API type.*soap.*available: rest"):
        enabled_types({"enabled": ["rest", "soap"]})


def test_settings_are_merged_across_types_without_duplicates(with_graphql):
    assert apitypes.repo_queries(with_graphql) == ["topic:openapi", "topic:graphql"]
    assert apitypes.definition_filenames(with_graphql) == ["schema.graphql"]
    assert apitypes.issue_keywords(with_graphql, ["api", "graphql"]) == ["api", "graphql", "openapi", "schema"]


def test_classifier_picks_the_best_matching_type(with_graphql, now):
    meta = {"full_name": "org/shop", "description": "Self-hosted shop backend with a GraphQL API", "topics": ["graphql"], "created_at": iso(500)}
    tree = [{"path": "schema.graphql", "type": "blob", "size": 400}]
    c = classify(meta, now=now, api_types=with_graphql, tree=tree)
    assert c.api_type == "graphql"
    assert c.per_type["graphql"] > c.per_type["rest"]
    assert "owns a GraphQL schema" in c.reasons


def test_discovery_queries_come_from_the_enabled_types(with_graphql, cfg, monkeypatch):
    seen_queries = []

    class RecordingGitHub:
        def search_repos(self, query, page=1, per_page=100, sort="updated"):
            seen_queries.append(query)
            return 0, []

        def search_issues(self, query, page=1, per_page=100):
            seen_queries.append(query)
            return 0, []

    gh = RecordingGitHub()
    list(source_candidates("repo_search", gh, cfg, random.Random(1), date(2026, 10, 12), with_graphql))
    list(source_candidates("help_requested", gh, cfg, random.Random(1), date(2026, 10, 12), with_graphql))
    assert any(q.startswith("topic:graphql ") for q in seen_queries)
    assert any(q.startswith("topic:openapi ") for q in seen_queries)
    assert any("graphql in:title" in q for q in seen_queries)
    assert any("openapi in:title" in q for q in seen_queries)


def test_llm_agreement_is_per_type():
    from docscout.llm.base import Review

    r = Review(project_type="serves_api", api_style="graphql", confidence=0.9, evidence="e", why="w")
    assert FakeGraphQL().llm_agrees(r)
    assert not RestApi().llm_agrees(r)
