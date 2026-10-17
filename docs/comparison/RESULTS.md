# Results: DocScout vs. an AI agent with a skill

The method is in [METHOD.md](METHOD.md). Round 1 ran on 14–15 Oct 2026, round 2 on 16 Oct, after the fixes round 1 pointed to, and round 3 on 17 Oct, after both sides changed. All ran over an unsteady connection.

**In short:**
- **Round 1:** the agent with the skill found better projects and stated its facts more accurately. Most of DocScout's misses came from fixable code checks.
- **Round 2, after the fixes:** DocScout's picks were worth acting on more often than the agent's (3 of 4, against 6 of 10), and 81% of its claims were right (50% in round 1). The agent still found twice as many projects worth acting on, with 96% of its claims right.
- **Round 3, both sides updated:** DocScout's fixed 60-repo run found nothing: 10 of the 13 healthy projects have a project website that may hold their docs, which it can't read yet. An extra run to 200 repos found 3; the author would act on 1 and maybe 2. The agent with the public skill found 10; the author would act on 4 and maybe 3. 95% of the agent's claims were right, against 83% of DocScout's.
- **Cost:** DocScout took about 8 minutes and no tokens per search, and it runs on its own every day. The agent took 46 minutes and 324,000 tokens. Gemma's reviews took the 7.6 GB laptop to its memory limit in both rounds.

| | Round 1: DocScout | Round 1: agent | Round 2: DocScout | Round 2: agent |
|---|---|---|---|---|
| Picks | 2 | 10 | 4 | 10 |
| Serve a REST API (author's grade) | 2 | 10 | 4 | 9 |
| **Author would act on them** | **1 (50%)** | **4 (40%)** | **3 (75%)** | **6 (60%)**, plus 1 maybe |
| Gap claims right | 10 of 20 (50%) | 79 of 81 (98%) | 17 of 21 (81%) | 92 of 96 (96%) |
| Time | 7.5 min | 1 h 59 min | 8.5 min | 46 min |
| Tokens | none | 375,826 | none | 323,775 |

## Test 1: the 58 labeled repos

| Setup | Precision | Recall | Mistakes |
|---|---|---|---|
| DocScout, code only | 76% | 90% | 12 |
| DocScout, code plus Gemma (`gemma4:e2b`) | 81% | 81% | 12 |
| **Agent with the skill (Claude Opus 5.5)** | **88%** | **97%** | **5** |

The agent's 5 mistakes:

| Repo | Hand label | Agent | Note |
|---|---|---|---|
| stoatchat/self-hosted | other | serves_api | A deployment repo: compose files that route `/api` to the API container. Defensible either way |
| up-banking/api | spam | serves_api | The official OpenAPI spec of a live hosted API |
| backenly/backenly | other | serves_api | |
| helpcode-ai/anythingmcp | api_tooling | serves_api | |
| nextagentx/trae-workbuddy-switch | serves_api | other | A desktop switcher with a local OpenAI-compatible gateway |

The agent took 46 minutes, 156,444 tokens, 63 tool calls and 171 GitHub calls (12.7 MB). Gemma takes about 51 s per repo on the laptop, about 49 minutes for 58 repos.

## Test 2: one search

| | DocScout | Agent with the skill |
|---|---|---|
| Repos checked in depth | 60 (69 looked at) | 40 |
| Picks | **2** (4 candidates; Gemma turned down 2) | **10** |
| Serve a REST API (author's grade) | 2 of 2 (4 of 4 candidates) | 10 of 10 |
| **Author would act on it** | **1 of 2** | **4 of 10** |
| Gap claims right (fact-check) | 10 of 20 (the 4 candidates) | 79 of 81 |
| Picks whose main claim is wrong | 1 of 2 (3 of the 4 candidates) | 0 of 10 (AzuraCast is half wrong) |
| Time | 3 min 19 s, plus 4 min 9 s of Gemma reviews | 1 h 59 min |
| GitHub calls | 223 | 334 (57.4 MB) |
| Tokens | none | 375,826 (192 tool calls) |
| Laptop memory | Gemma took free memory down to 0.24 GB and filled all 2 GB of swap | none |

### The picks, with the author's grades

| Project | From | Author would act on it | Fact-check |
|---|---|---|---|
| project-zot/zot | agent | yes | 5 of 5 right |
| babybuddy/babybuddy | agent | yes | 10 of 10 right |
| the-momentum/open-wearables | agent | yes | 7 right, 1 partly (draft PR #1158 was closed, not open) |
| jupyter-server/jupyter_server | agent | yes | 11 of 11 right |
| AzuraCast/AzuraCast | agent | no | 7 right, 1 wrong ("257 of 269 operations have no example"; really 3–6; DocScout's 3 was right) |
| dagucloud/dagu | agent | no | 7 of 7 right |
| chrisvel/tududi | agent | no | 7 of 7 right |
| Kpa-clawbot/CoreScope | agent | no | 5 of 5 right |
| muety/wakapi | agent | no | 10 of 10 right |
| modoboa/modoboa | both | no | agent 10 of 10; DocScout 9 of 10 (it called the drf-spectacular output "hand-written") |
| ChurchCRM/CRM | DocScout | yes | 1 right, 4 wrong, 1 partly: it has generated OpenAPI specs and a hosted API page, and the "prose docs" were an AI-agent skill file |
| traceroot-ai/traceroot | DocScout candidate; Gemma said "other" | yes | wrong: it has a 54-operation spec, and issue #2579 is a feature request, not docs |
| mycelium-labs/mycelium | DocScout candidate; Gemma said "library" | no | wrong: the spec is generated in code, and issue #279 is a bug |

Notes:
- **Gemma's review was a coin flip here.** It turned down traceroot, which the author would act on and which does serve an API. It accepted modoboa, which the author wouldn't act on.
- **The grading was only partly blind.** Before the grading, I named 4 of the agent's picks (dagu, jupyter_server, tududi and AzuraCast) in a message, and the style of the gap lines may have hinted at the source.

### What the author wants: docs you can read without installing anything

The author's reason for most "no" answers: the API reference only appears once you install and run the app (Swagger UI). The author prefers projects whose docs are published as pages, even if only as a README on GitHub.

A check on the 13 graded repos (the repo's homepage, docs-site config such as mkdocs, Sphinx or Mintlify, and a separate docs repo) found:
- a docs site for **all 6** projects the author would act on;
- a docs site for 3 of the 7 they wouldn't: modoboa, dagu and tududi.

So a docs site is a good ranking signal, but not a filter on its own.

## Why DocScout missed or got things wrong

| Cause | Effect |
|---|---|
| Spec files are only found when "openapi" or "swagger" is in the **file name** ([rest.py](../../docscout/analyze/apitypes/rest.py) `definition_pattern`) | Missed 4 specs: dagu `api/v1/api.yaml`, jupyter_server `services/api/api.yaml`, traceroot `backend/rest/openapi/public.json`, ChurchCRM `docs/openapi/generated/*.yaml` |
| An AI-agent instruction file (`.agents/skills/…`) counted as API docs | ChurchCRM's "prose docs" and their counts were wrong |
| Issues labeled "help wanted" or "good first issue" with "api" in the title count as docs requests | A feature request (traceroot #2579) and a bug (mycelium #279) were shown as "maintainers asked for help" |
| Specs exported by a framework (drf-spectacular) without a marker show as hand-written | modoboa's suggestion should have been "edit the code annotations" |
| A spec written in code (swagger-jsdoc) can't be read | tududi gave only "check manually" |
| "Docs elsewhere" is treated as a reason **not** to report a repo | The opposite of what the author wants |

Two DocScout bugs also turned up, both fixed in 270fbb4:
- `run --limit 0` started a full search;
- report files were named after the UTC date.

## Round 2 (16 Oct): after fixing DocScout

The rules are in [METHOD.md](METHOD.md#round-2-16-oct-after-fixing-docscout):
- both sides were told the author prefers docs published as pages;
- the agent skipped the 13 projects graded in round 1;
- the grading was fully blind this time.

DocScout ran with the fixes from 43965ee. Its clock was set to the round 1 start, but its sample still changed: once the non-docs help requests were gone, other repos filled the 60-repo budget.

| | DocScout | Agent with the skill |
|---|---|---|
| Repos checked in depth | 60 (73 looked at) | 34 |
| Picks | 4 (Gemma accepted all 4) | 10 |
| Serve a REST API (author's grade) | 4 of 4 | 9 of 10 (flowctl: no) |
| **Author would act on it** | **3 of 4** | **6 of 10**, plus 1 maybe |
| Gap claims right (fact-check) | 17 of 21 (81%) | 92 of 96 (96%) |
| Picks whose main claim is wrong | 1 of 4 (VoucherVault) | 0 of 10 |
| Time | 4 min 13 s search, plus 4 min 14 s of Gemma reviews | 45 min 55 s |
| GitHub calls | 196 | 584 (38.4 MB) |
| Tokens | none | 323,775 (158 tool calls) |
| Laptop memory | Gemma took free memory down to 0.20 GB and filled all 2 GB of swap | none |

### The picks, with the author's grades

| Project | From | Author would act on it | Fact-check |
|---|---|---|---|
| openziti/ziti | DocScout | yes | 6 right, 1 partly (openziti/ziti-browzer-doc documents another project, BrowZer) |
| Local-Settle/local-settle-backend | DocScout | yes | 4 right, 1 wrong (the API is also documented in `docs/*.md`, not only the README) |
| eugenioenko/autentico | DocScout | yes | 7 right, 1 wrong ("hand-written": `docs/swagger.json` is generated by swag, as `docs/docs.go` says) |
| l4rm4nd/VoucherVault | DocScout | no | wrong: "no API docs", but the project's GitHub wiki has an API endpoints page |
| GIScience/openrouteservice | agent | yes | 8 right, 1 wrong (PR #2324 is a feature PR, not docs only) |
| snapotter-hq/SnapOtter | agent | yes | 13 right, 1 wrong (60 outside PRs merged since April, not 16) |
| OpnForm/OpnForm | agent | yes | 9 right, 1 partly, 1 wrong (open PR #1182 does change the API reference) |
| sipcapture/homer | agent | yes | 12 of 12 right |
| eikek/docspell | agent | yes | 7 of 7 right |
| johanohly/AirTrail | agent | yes | 8 of 8 right |
| fossar/selfoss | agent | maybe | 12 of 12 right |
| DSpace/DSpace | agent | no | 7 of 7 right |
| FOSSBilling/FOSSBilling | agent | no | 8 of 8 right |
| cvhariharan/flowctl | agent | no (doesn't serve an API, per the author) | 8 of 8 right |

### What round 2 shows

- **The fixes worked.** DocScout's claims were right far more often (81%, up from 50%), and every pick served an API. Its picks were worth acting on more often than the agent's.
- **The agent still finds more.** It found twice as many projects worth acting on, and it made fewer factual mistakes. One of its wrong claims matters for a writer: it said no open PR touched OpnForm's API docs, but #1182 does.
- **Gemma agreed with the author on all 4 this time.** In round 1 it agreed on 2 of 4 (it turned down traceroot and mycelium, which the author said serve an API).
- **DocScout's remaining misses:**
  - a spec generated by swag still shows as hand-written, because the marker sits in the neighboring `docs.go`;
  - docs in a GitHub wiki aren't read, so "no docs found" was wrong;
  - a docs repo for another product from the same owner was counted;
  - the only pick the author rejected is the unverified "no docs found" kind, the weakest evidence DocScout reports.

## Round 3 (17 Oct): both sides updated

The rules are in [METHOD.md](METHOD.md#round-3-17-oct-both-sides-updated). DocScout ran at `1aaec67` with Gemma 4 31B (26B when busy), and the agent followed the public skill ([skills/find-api-docs-to-contribute/SKILL.md](../../skills/find-api-docs-to-contribute/SKILL.md)). Both skipped the 33 projects graded or seen before. The grading was blind.

**DocScout's fixed run found nothing.** It checked 60 repos (69 looked at), 13 passed the health checks, and none was reported:
- 10 have a project website that may hold their docs (traggo.net, misago-project.org, kuzzle.io…) and no help request. DocScout can't read websites yet (M4), so it reports those only when maintainers asked for help. Whether their API docs are really on those sites wasn't checked.
- 1 was dropped by the new size cutoff (cybersecify/OpenEASD, 3 endpoints needing work), 1 had no docs at all, and 1 scored below the confidence threshold.
- The method's note, written before grading, said "11 of them"; it counted OpenEASD's website too.

As written into the method before grading, one extra run continued the same search to 200 repos, the hosted version's daily setting. Its picks are DocScout's column below.

| | DocScout (extra run, 200 repos) | Agent with the public skill |
|---|---|---|
| Repos checked in depth | 200 (256 looked at), 48 passed the health checks | 35 (about 830 pre-screened from metadata) |
| Picks | 3 (Gemma reviewed 7, accepted 3) | 10 |
| Serve a REST API (author's grade) | 3 of 3 | 9 of 10 (Gokapi: no, "can't find the API doc page") |
| **Author would act on it** | **1 of 3**, plus 2 maybe | **4 of 10**, plus 3 maybe |
| Gap claims right (fact-check) | 25 of 30 (83%) | 180 of 189 (95%) |
| Picks whose main claim is wrong | 2 of 3 (zowe, free-llm-api-hub) | 1 of 10 (TimeTracker's counts), plus 1 partly (wizarr) |
| Healthy and not claimed (objective check) | 3 of 3 | 10 of 10 |
| Time | 2 min 51 s for the fixed run, plus 16 min 48 s for the extra run | 1 h 19 min 31 s |
| GitHub calls | 182 + 492 | not logged (plain `curl`, as the method said) |
| Tokens | none (7 Gemma reviews, plus its claim questions) | 361,198 (139 tool calls) |

### The picks, with the author's grades

| Project | From | Author would act on it | Fact-check |
|---|---|---|---|
| pacocartones/free-llm-api-hub | DocScout | yes | 6 right, 1 wrong: "no endpoints documented in the repo", but `docs/api.md` documents the `/api/v1/*.json` endpoints |
| eikek/sharry | DocScout | maybe ("the REST API docs page isn't even rendered from the spec") | 13 right, 3 wrong: 62 operations, not 57 (5 paths `$ref` others with `%7Bid%7D`); 4 with undescribed parameters, not 2; 12 (or 8, excusing 204s) without a success schema, not 6 |
| zowe/api-layer | DocScout | maybe | 6 right, 1 wrong: "no endpoints documented in the repo", but `caching-service/README.md` has an endpoints table and `zaas-api-doc.json` is a 6-operation spec. Issue #4159 is already partly fixed by maintainer PR #4515 |
| DRYTRIX/TimeTracker | agent | yes | 28 right, 3 wrong: 332 routes, not 327; 282 undocumented, not 279; webhooks has a section |
| timothepoznanski/poznote | agent | yes | 18 of 18 right (see the note on examples) |
| ampache/ampache | agent | yes | 19 right, 1 wrong: ampache.org/rest is a prose page; the Swagger UI is at /rest/swagger/ |
| ecosyste-ms/awesome | agent | yes | 24 right, 1 wrong: at least 4 routed endpoints are missing from the spec, not 2 |
| AtalayaLabs/OxiCloud | agent | maybe | 15 right, 1 wrong: the docs site embeds Swagger UI, not Redoc |
| octobox/octobox | agent | maybe | 22 of 22 right |
| kuvasz-uptime/kuvasz | agent | maybe ("response examples, but no request examples") | 13 of 13 right under the agent's own definition of an example (see below) |
| jordan-dalby/ByteStash | agent | no ("need to run the app to see the API docs") | 21 right, 1 wrong: the wiki has 6 pages, not 5 |
| wizarrrr/wizarr | agent | no ("need to run the app to see the API docs") | 7 right, 2 wrong: `API.md` shows more than section titles; 14 endpoints are documented only in Swagger UI, not 16 |
| Forceu/Gokapi | agent | no (and not an API, per the author) | 13 of 13 right |

**Examples:** the skill never says what counts as an example, and the agent counted examples on parameters, media types and top-level schemas only. Redoc and Swagger UI also show example values set on schema fields as example bodies, which is what the author saw on kuvasz. Counted that way, kuvasz has 44 of 82 operations without examples (not 81), octobox 9 of 18 (not 16), poznote 103–115 of 172 (not 159) and Gokapi 12 of 36 (not 36). DocScout's check already counts examples anywhere in an operation, following `$ref`s.

### What round 3 shows

- **The agent still finds more, and states its facts more accurately.** It found 4 projects worth acting on against DocScout's 1, and 95% of its claims were right against 83%. It costs far more: 1 h 20 min and 361,000 tokens, against about 20 minutes and no tokens.
- **DocScout's biggest limit is docs it can't read.** In its fixed 60-repo run, 10 of the 13 healthy projects had a project website that may hold their docs, and DocScout skipped them all. Reading those sites (M4) is the largest missing piece.
- **Both sides misjudge who is an outsider.** GitHub shows maintainers whose org membership is private as CONTRIBUTOR. zowe/api-layer's "63 outside PRs merged" are almost all by the 7 people who merge PRs there; only 1 is a real outsider's. The agent found the same on ethersphere/bee and drasi, and dropped them by also excluding anyone who merges PRs.
- **Published docs decide what the writer will act on.** The author turned down both agent picks whose API reference is only in the running app (ByteStash, wizarr), although the skill already ranks those lower. On sharry, DocScout measured the spec while the published API page isn't built from it.
- **DocScout's new mistakes:**
  - endpoints written without an HTTP method (`/api/v1/no-card.json`), and endpoint tables in a sub-folder README, aren't found, so "no endpoints documented" was wrong twice;
  - path items that `$ref` other paths through URL-encoded names (`%7Bid%7D`) aren't followed;
  - a shields.io badge URL was quoted as an AI-contribution policy (the real `AI_POLICY.md` welcomes AI-assisted work), and "local setup: unclear" missed the steps in CONTRIBUTING.md;
  - "Docs published: eikek.github.io" names a host that returns 404; the docs are at eikek.github.io/sharry.
- **Gemma's claim checks agreed with the objective check:** none of the 3 DocScout picks was claimed.
