import pytest

from docscout.analyze.tree import has_container_setup, has_contributing
from docscout.analyze.apitypes.rest import RestApi, find_endpoints, mentions_rest_api
from docscout.analyze.safe_yaml import UnsafeYAML, load_untrusted


def blob(path, size=1000):
    return {"path": path, "type": "blob", "size": size}


def test_find_specs_keeps_owned_and_skips_vendored_test_and_example_specs():
    tree = [
        blob("api/openapi.yaml"),
        blob("openapi.json"),
        blob("docs/swagger-v2.yml"),
        blob("vendor/stripe/openapi.yaml"),
        blob("tests/fixtures/openapi.yaml"),
        blob("examples/petstore/openapi.yaml"),
        blob("node_modules/x/swagger.json"),
        blob("third_party/swagger.json"),
        blob("big/openapi.yaml", size=3 * 1024 * 1024),
        {"path": "openapi", "type": "tree"},
        blob("src/openapi_client.py"),
    ]
    assert [s.path for s in RestApi().find_definitions(tree)] == ["openapi.json", "api/openapi.yaml", "docs/swagger-v2.yml"]


def test_tree_helpers():
    tree = [blob("CONTRIBUTING.md"), blob("compose.yaml")]
    assert has_contributing(tree) and has_container_setup(tree)
    assert has_contributing([blob(".github/CONTRIBUTING.md")])
    assert not has_container_setup([blob("src/docker.py")])


def test_find_endpoints_from_prose_tables_and_curl():
    text = """
## API
GET /api/users
`POST /api/users/{id}`
| Method | Endpoint |
|--------|----------|
| DELETE | `/api/users/{id}` |
curl -X PATCH https://example.com/api/items/1 -d '{}'
Use GET requests sparingly.
"""
    assert find_endpoints(text) == {
        ("GET", "/api/users"),
        ("POST", "/api/users/{id}"),
        ("DELETE", "/api/users/{id}"),
        ("PATCH", "/api/items/1"),
    }
    assert mentions_rest_api("It exposes a RESTful API.")
    assert not mentions_rest_api("A library with a clean API.")


def test_install_commands_are_not_api_endpoints():
    # mycart (17 Oct): its install line was counted as "GET /shurco/mycart/main/scripts/install".
    text = """
curl -L https://raw.githubusercontent.com/shurco/mycart/main/scripts/install | sh
curl -fsSL https://get.docker.com | sudo sh
curl https://example.com/setup.sh | bash
curl -LO https://github.com/org/app/releases/download/v1.2/app.tar.gz
curl -X GET https://demo.example.com/api/v1/crypto | jq .
"""
    assert find_endpoints(text) == {("GET", "/api/v1/crypto")}


def test_yaml_aliases_rejected():
    with pytest.raises(UnsafeYAML):
        load_untrusted("a: &x [1, 2]\nb: *x\n")
    assert load_untrusted("openapi: 3.1.0\ninfo: {title: t}") == {"openapi": "3.1.0", "info": {"title": "t"}}
    with pytest.raises(UnsafeYAML):
        load_untrusted("x" * 100, max_bytes=10)
