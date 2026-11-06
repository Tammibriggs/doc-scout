"""M6 step 6c: a claim covers only the gaps it would close. PRs that change the measured docs file
are measured; comments, and PRs on a generated spec, are Gemma's call, one gap at a time; an
offer counts for 30 days from the person's last comment. No test reaches GitHub or a model."""

from datetime import timedelta
from pathlib import Path

from conftest import iso

from docscout.analyze import pr_measure
from docscout.analyze.apitypes.openapi import score_spec
from docscout.hosted.picks import pick, weekly_picks
from docscout.llm import claims
from docscout.llm.base import Claim, ClaimCheck
from docscout.run.db import Store, StoredFinding

SPECS = Path(__file__).parent / "fixtures" / "specs"
BARE, DESCRIBED = (SPECS / "bare.yaml").read_bytes(), (SPECS / "bare_described.yaml").read_bytes()
HEAD, PATH = "c" * 40, "api/openapi.yaml"


def pr(number, *, files=(PATH,), changed=None, login="writer", head=HEAD, title="docs: describe the endpoints"):
    return {"number": number, "title": title, "head": {"ref": "docs", "sha": head}, "base": {"sha": "b" * 40}, "files": list(files),
            "changed_files": len(files) if changed is None else changed, "user": {"login": login, "type": "User"},
            "created_at": iso(3), "updated_at": iso(1)}  # fmt: skip


def comment(cid, body, login, days_ago, association="NONE"):
    return {"id": cid, "body": body, "user": {"login": login, "type": "User"}, "created_at": iso(days_ago), "author_association": association}


class GitHub:
    """Open PRs, comments on issue #12, and the spec: DESCRIBED at the PRs' head, BARE elsewhere."""

    def __init__(self, pulls=(), comments=()):
        self.pulls, self.comments, self.compared, self.fetched = list(pulls), list(comments), [], []

    def list_open_pulls(self, name):
        return self.pulls

    def list_issue_comments(self, name, number):
        return self.comments if number == 12 else []

    def compare(self, name, base, head):
        self.compared.append(head)
        files = next((p["files"] for p in self.pulls if p["head"]["sha"] == head), [])
        return {"merge_base": "a" * 40, "files": files, "complete": True}

    def get_file(self, name, path, ref=None, max_bytes=None):
        self.fetched.append(ref)
        return DESCRIBED if ref == HEAD else BARE


class Model:
    """Claims the comments and PRs whose text contains a scripted phrase, for the scripted gaps."""

    name = "openai_compatible:gemma-4-31b-it"

    def __init__(self, phrases=None):
        self.phrases, self.contexts = phrases or {}, []

    def claims(self, ctx):
        self.contexts.append(ctx)
        return ClaimCheck(claims=[Claim(item=label, reason="r", gaps=gaps) for label, text in ctx.items for phrase, gaps in self.phrases.items() if phrase in text])


def finding(*, generated=False, issues=None):
    report = score_spec(BARE, PATH)
    gap = {"kind": "spec", "score": 60, "location": PATH, "generated": generated, "summary": "OpenAPI 3.0.3, 4 operations",
           "findings": [{"text": f.text, "examples": f.examples, "more": f.more, "check": f.check} for f in report.findings],
           "effort_units": report.failing_operations}  # fmt: skip
    help_request = {"number": 12, "title": "Document the checks endpoints", "help": {"verdict": "this_work", "verified": True}}
    return StoredFinding("org/app", 50, {"gap": gap, "issues": [help_request] if issues is None else issues, "checks": {}}, 1, 1)


# ---------------------------------------------------------------------- measuring a PR


def test_a_pr_claims_what_it_fixes_not_what_it_adds_or_removes():
    before = score_spec(BARE, PATH)
    more = BARE.replace(b"paths:\n", b"paths:\n  /extra:\n    get:\n      responses:\n        \"200\": {description: ok}\n")
    fixed, fields = pr_measure.spec_fixes(before, score_spec(more, PATH))
    assert fixed == {} and fields == []  # a new, undocumented operation fixes nothing
    fewer = score_spec(BARE.replace(b"    delete:\n      responses:\n        \"204\":\n          description: deleted\n", b""), PATH)
    assert pr_measure.spec_fixes(before, fewer) == ({}, [])  # nor does removing one
    fixed, _ = pr_measure.spec_fixes(before, score_spec(DESCRIBED, PATH))
    assert fixed == {"description": ["GET /checks", "POST /checks", "GET /checks/{id}", "DELETE /checks/{id}"]}
    served = score_spec(BARE.replace(b"paths:", b"servers: [{url: 'https://x.example'}]\npaths:"), PATH)
    assert pr_measure.spec_fixes(before, served)[0] == {"servers": ["the spec"]}


def test_a_pr_is_measured_only_when_it_changes_the_measured_file():
    gh = GitHub()
    gap = finding().details["gap"]
    untouched = pr_measure.measure(gh, "org/app", gap, pr(1, files=["src/app.py"]))
    assert untouched["touches"] is False and gh.compared == [] and gh.fetched == []  # the PR's file list settles it
    gh.pulls = [pr(2, files=["src/app.py"] * 10, changed=40)]  # only 10 of 40 files listed: GitHub is asked
    assert pr_measure.measure(gh, "org/app", gap, gh.pulls[0])["touches"] is False and gh.compared == [HEAD]
    gh.pulls = [pr(3)]
    touched = pr_measure.measure(gh, "org/app", gap, gh.pulls[0])
    assert touched["touches"] and touched["fixed"]["description"][0] == "GET /checks" and gh.fetched == ["a" * 40, HEAD]  # the merge base, then the PR


def test_prose_prs_are_measured_per_endpoint():
    before = b"## List checks\n\n`GET /api/checks`\n\nReturns the checks.\n"
    after = before + b"\n```bash\ncurl https://x.example/api/checks\n```\n\nResponse:\n\n```json\n[{\"id\": 1}]\n```\n"
    fixed = pr_measure.prose_fixes("docs/api.md", before, after)
    assert fixed.get("request_example") == ["GET /api/checks"]


def test_the_work_left_counts_operations_with_any_gap_nobody_has_taken():
    failing = {"description": ["GET /a", "GET /b"], "errors": ["GET /a"]}
    assert pr_measure.work_left(failing, {}, set()) == (2, 2)
    assert pr_measure.work_left(failing, {"description": {"GET /a", "GET /b"}}, set()) == (1, 2)  # GET /a still lacks errors
    assert pr_measure.work_left(failing, {"description": {"GET /a", "GET /b"}}, {"errors"}) == (0, 2)  # an offer takes the errors


# ---------------------------------------------------------------------- the claim check


def test_a_measured_pr_leaves_the_pick_partly_claimed(now):
    gh, model = GitHub(pulls=[pr(3), pr(4, files=["src/app.py"], title="feat: add webhooks")]), Model()
    f = finding(issues=[])
    assert claims.check(gh, model, f, now, min_units=1)  # the test spec has only 4 operations
    c = f.details["checks"]
    assert c["claimed"] == ['Open PR #3 "docs: describe the endpoints" adds descriptions to 4 operations']
    assert f.details["claims"]["work_left"] == 4 and f.details["claims"]["work"] == 4  # every operation still has other gaps
    assert not c["claimed_out"] and model.contexts == []  # PRs on a hand-written spec are measured: the model isn't asked
    compared = list(gh.compared)
    gh.comments = [comment(1, "thanks!", "fan", 1)]  # something changed, but not the PRs' head commits
    gh.pulls[0]["updated_at"] = iso(0)
    assert claims.check(gh, Model(), f, now, min_units=1) and gh.compared == compared  # stored measurements reused


def test_offers_count_for_30_days_after_the_persons_last_comment(now):
    offers = [comment(1, "I'll take this one", "ana", 40), comment(2, "I can take this too", "bo", 40), comment(3, "Still on it, PR soon", "bo", 10),
              comment(4, "Can I help?", "cy", 2), {**comment(5, "Assigned!", "bot", 1), "user": {"login": "drips-wave[bot]", "type": "Bot"}}]  # fmt: skip
    gh = GitHub(pulls=[pr(7, files=["src/x.py"], login="cy")], comments=offers)
    model = Model({"take this": ["response_example"], "Can I help": ["errors"], "Assigned": ["errors"]})
    f = finding()
    assert claims.check(gh, model, f, now)
    c = f.details["checks"]
    assert c["claimed"] == ["bo on #12 (" + iso(40)[:10] + ") offered to work on response examples: r"]  # bo commented 10 days ago
    assert c["stale_offers"] == ["ana offered on #12 (" + iso(40)[:10] + ") to work on response examples, with no PR or comment since: ask whether they're still on it"]
    assert [o["author"] for o in f.details["claims"]["offers"] if not o["live"]] == ["ana", "cy"]  # cy has an open PR: it's measured instead
    assert "drips-wave[bot]" not in "\n".join(text for _, text in model.contexts[0].items)  # bots' comments aren't read


def test_offers_covering_the_work_move_the_pick_down(tmp_path, now):
    gh = GitHub(comments=[comment(1, "I'll take this, all of it", "ana", 2)])
    keys = ["description", "parameters", "response_example", "success_schema", "errors"]
    f = finding()
    assert claims.check(gh, Model({"take this": keys}), f, now)
    assert f.details["claims"]["work_left"] == 0 and f.details["checks"]["claimed_out"]
    store = Store(tmp_path / "docscout.db")
    run = store.start_run(now)
    for name, details in (("org/taken", f.details), ("org/free", finding().details)):
        store.save_repo(name, now)
        store.save_finding(run, name, now, api_type="rest", kind="spec", gap=60, score=60 if name == "org/taken" else 50, effort="S", details=details)
        store.set_status(name, "reported", now)
    assert [p["full_name"] for p in weekly_picks(store, now)] == ["org/free", "org/taken"]  # the better score goes last: someone is on it
    card = pick(StoredFinding("org/taken", 60, f.details, 1, reported=now.isoformat()), 1, now)
    assert card["claimed_out"] and card["work_left"] == 0 and card["work"] == 4


def test_gemma_judges_prs_on_a_generated_spec_that_dont_change_it(now):
    gh = GitHub(pulls=[pr(5, files=["app/routes/users.py"], title="docs: docstrings and examples for the user routes")])
    model = Model({"docstrings": ["description", "response_example"]})
    f = finding(generated=True, issues=[])
    assert claims.check(gh, model, f, now)
    assert [label for label, _ in model.contexts[0].items] == ["PR #5"]
    assert f.details["checks"]["claimed"] == ['Open PR #5 "docs: docstrings and examples for the user routes" (descriptions, response examples): r']


def test_a_pr_with_no_activity_for_90_days_claims_nothing_and_isnt_measured(now):
    old = {**pr(8), "updated_at": iso(120), "created_at": iso(300)}
    gh = GitHub(pulls=[old])
    f = finding(issues=[])
    assert claims.check(gh, Model(), f, now, min_units=1)
    assert f.details["checks"]["claimed"] == [] and gh.compared == [] and f.details["claims"]["prs"][0]["stale"]


def test_large_specs_parse_fast_and_still_refuse_aliases():
    import json
    import time

    from docscout.analyze.safe_yaml import UnsafeYAML, load_untrusted

    big = {"openapi": "3.0.3", "paths": {f"/items/{i}": {"get": {"summary": f"Item {i}", "responses": {"200": {"description": "ok"}}}} for i in range(3000)}}
    as_json = json.dumps(big).encode()
    started = time.monotonic()
    assert load_untrusted(as_json) == big and time.monotonic() - started < 1  # JSON: the JSON parser
    assert load_untrusted(b"{a: 1}") == {"a": 1}  # YAML that only starts like JSON
    try:
        load_untrusted("a: &x [1]\nb: *x\n")
        raise AssertionError("an alias was accepted")
    except UnsafeYAML as exc:
        assert "aliases are not allowed (line 2)" in str(exc)


def test_a_claim_that_takes_no_operation_off_gets_no_chip(now):
    gh = GitHub(pulls=[pr(3)])
    f = finding(issues=[])
    assert claims.check(gh, Model(), f, now, min_units=1)
    card = pick(StoredFinding("org/app", 50, f.details, 1, reported=now.isoformat()), 1, now)
    assert card["claimed"] and not card["partly"]  # descriptions for all 4, but each still has other gaps: 4 of 4 left
    f.details["claims"]["work_left"] = 1
    assert pick(StoredFinding("org/app", 50, f.details, 1, reported=now.isoformat()), 1, now)["partly"]
