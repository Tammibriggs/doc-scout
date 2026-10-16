# Results: DocScout vs. an AI agent with a skill

The method is in [METHOD.md](METHOD.md). Round 1 ran on 14–15 Oct 2026, and round 2 on 16 Oct, after the fixes round 1 pointed to. Both ran over an unsteady connection.

**In short:**
- **Round 1:** the agent with the skill found better projects and stated its facts more accurately. Most of DocScout's misses came from fixable code checks.
- **Round 2, after the fixes:** DocScout's picks were worth acting on more often than the agent's (3 of 4, against 6 of 10), and 81% of its claims were right (50% in round 1). The agent still found twice as many projects worth acting on, with 96% of its claims right.
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
| Spec files are only found when "openapi" or "swagger" is in the **file name** ([rest.py](../../docscout/apitypes/rest.py) `definition_pattern`) | Missed 4 specs: dagu `api/v1/api.yaml`, jupyter_server `services/api/api.yaml`, traceroot `backend/rest/openapi/public.json`, ChurchCRM `docs/openapi/generated/*.yaml` |
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
