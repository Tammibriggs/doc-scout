# DocScout plan

DocScout finds open-source projects that **(a)** serve an API, **(b)** have documentation gaps you can fix, and **(c)** are likely to accept your pull request. Once installed, it runs every day without being started by hand and gives you a short ranked list. Each item lists the exact gaps, links to start from, and warnings about anything that could get the PR rejected. It starts with REST APIs, and other API types plug in as modules.

**Deadline: Monday 19 October 2026**, one week from 12 October. **Target: finish by Thu 15 October** (Fri 16 as a buffer), since M0, M1 and M3 finished early.

**Submission:** the [DEV Hacktoberfest Open Source AI Challenge, Week 2 "Side Hustle"](https://dev.to/devteam/join-the-hacktoberfest-open-source-ai-challenge-side-hustle-2550-in-prizes-across-18-winners-55ba): "Build something with open-weight models or open-source AI that someone would actually pay for", where "the open pieces should be what makes your project work". Due **18 Oct, 11:59 PM PDT (Mon 19 Oct, 07:59 WAT)**. It needs a DEV post (writing quality is weighted most), a demo video or deployed link, and the code. A first user is a bonus. It fits the Gemma category, since DocScout runs Gemma 4 locally. That's why M2 makes Gemma required, not optional.

## 1. Status and timeline

**Build stages (milestones).** Each stage is usable on its own. M3 (daily runs) comes **before** M2 (LLM), so the unattended test can run while M2 is built. Each stage lists what must ship by the deadline and what ships only if there's time.

| Stage | Must ship | If time allows | Dates |
|---|---|---|---|
| **M0. Prove discovery** | ✅ Done (13 Oct). Accuracy check passed, and the local LLM works (section 2) | — | Mon 12 – Tue 13 Oct (morning) |
| **M1. Useful manual report** | ✅ Done on branch `m1-report` (Mon 12 Oct, ahead of schedule): OpenAPI spec gap scorer; endpoint completeness in prose docs; "docs elsewhere / generated, check manually" flag; generated-spec warning; scoring with your languages ranked higher; SQLite (seen, ignored, done); safe Markdown report; `run`, `ignore`, `done`, `score`. ✅ Exit check passed (16 Oct): in the blind grading of comparison round 2, you'd act on 3 of DocScout's 4 picks | ✅ Also done: claim check (open docs PRs, "I'll take this"); CLA, DCO and AI-policy notes; local-setup note | Mon 12 – Tue 13 Oct |
| **M3. Daily runs on Linux** | ✅ Built on branch `m3-daily` (Tue 13 Oct, three days early): `run --if-due`, file lock, offline check and resume, a cursor through the search slices, token, settings and repeated-failure alerts, `schedule install/uninstall/status` for systemd, `status`; **notifications when the day's run starts** ("your computer may be slower for about N minutes", estimated from earlier runs) **and when it finishes** (with the report path), each turned off with `docscout set`. Also: GitHub lists fetched through GraphQL, so a run downloads far less (section 5). ✅ Exit check passed: the unattended test | ✅ Also done: quiet-day rules; "pool running dry" notification | Tue 13 Oct |
| **M2. Gemma required** (branch `m2-llm`, built in a separate worktree) | ✅ First, fewer noisy items (section 9). Then ✅: **Gemma reviews every repo that passes the health checks** (up to `reviews_per_run` a day, most promising first): it decides whether the project really has an API worth documenting, with the 0.8 cap, and writes why it matters plus up to 3 first steps. **Only reviewed repos are reported.** Unreviewed ones are held, not dropped, and reviewed later. A memory check runs before loading the model. `docscout draft owner/repo` writes a first message to the maintainers for a project you've chosen. **Measured on the 58 labels**, with and without Gemma, and with thinking off and on. **Compared with an AI agent given a skill** (section 2), which led to the fixes of 16 Oct. ✅ Merged into `main` on 16 Oct. ⏳ Still to check: you rate at least 7 of 10 of Gemma's first steps as useful (section 18) | | Wed 14 – Fri 16 Oct |
| Unattended test | ✅ Passed. **2 days** from `docscout schedule install`: no manual starts, survives a reboot and going offline. Result: 5 scheduled runs (13–16 Oct), 2 restarts and 1 lost connection, all recovered without manual starts. M2 was built in a separate worktree, so the daily runs kept using the M3 code | | Tue 13 – Thu 15 Oct |
| Polish and wrap-up | ✅ `m1-report`, `m3-daily` and `m2-llm` merged into `main` on 16 Oct (a fast-forward: each branch builds on the one before). From then on, the daily runs use the Gemma version. README, demo report | | Thu 15 Oct (Fri 16 buffer) |
| **Hosted version** (branch `hosted`) | ✅ Built (16 Oct), section 20: a website that shows the picks from the last 7 days, the top 3 free and the rest for $3 a month (Stripe Checkout, test mode); a daily Render cron job running DocScout with Gemma 4 31B on Google's API; MongoDB Atlas for DocScout's memory, the picks and the subscriptions. ✅ Gemma 4 31B measured on the 58 labels: 85% / 90%, against 81% / 81% for `e2b` (section 2). ✅ Deployed (16–17 Oct): the code is public on GitHub, and the daily job runs on Render (on schedule since 17 Oct, 04:15 UTC). ⏳ A test payment on the live site | | Fri 16 – Sat 17 Oct |
| Challenge submission | Demo video; a real docs contribution made with a DocScout pick (the "first user"); the DEV post, written in your own voice | | Fri 16 – Sun 18 Oct |
| **Deadline** | | | **Mon 19 Oct** |
| **M4. Read external docs** | | **After the deadline** | |
| **M5. macOS and Windows support** | launchd and Task Scheduler setup, notifications and file lock on both, CI on 3 operating systems, `pipx` packaging, a fresh-install test on real machines | **After the deadline** | |

**If the schedule slips:** the "if time allows" items go first, then M2 shrinks to first steps only. M1's must-ship items stay, because without them the tool can't tell you what to fix.

**macOS and Windows are planned, not dropped.** Everything built so far is already plain cross-platform Python:
- user folders come from `platformdirs`;
- the secrets file is created private on Unix, and the permission call is skipped on Windows;
- the windowless `docscout-bg` entry point exists.

M3 builds scheduling behind a small per-OS interface (`scheduler/linux.py`), so M5 only adds `macos.py` and `windows.py`. Their exact settings are already worked out (section 14).

**How work is saved:** `main` holds finished work. Each stage gets its own branch (`m1-report`, `m2-llm`, …), merged into `main` when its exit check passes. There's a commit at each key stage, always with tests passing, and never with secrets or local samples.

## 2. M0 results (13 October)

**Accuracy on 58 hand-labeled repos.** The labels are in `tests/fixtures/labeled_repos.csv`, and `docscout eval tests/fixtures/labeled_repos.csv --reclassify` repeats this check whenever the classifier changes, with the repo data cached after the first run.

| | Precision | Recall |
|---|---|---|
| When sampled | 71% | 71% |
| After the fixes below | **76%** | **90%** |

| Source | Precision now |
|---|---|
| awesome_selfhosted | 68% |
| help_requested | 77% |
| repo_search | 100% |

All three sources are above 50%, so all stay on.

**What changed:**
- **The spam rule** (more than 15 topics counted as spam only on new repos; spam re-checked after fetching full details). This recovered 7 real API apps that had been labeled spam.
- **"specification" is no longer a tool word.**
- **A repo counts as an API project from 0.6 confidence, not 0.5.** At 0.5 it was 69% precision and 94% recall.
- **Rejected: requiring explicit API evidence.** It reached 72% precision but only 68% recall, because real API apps like 2FAuth and Squidex never mention their API in their description or README.

**Remaining false positives** are apps without an API that look like apps with one (memories, sish, django-wiki, Zero-K). Telling them apart needs the README read, which is the LLM's second-opinion job in M2. Until M2, repos between 0.4 and 0.6 aren't reported.

**LLM benchmark** (`gemma4:e2b`, other apps closed):
- 44.8 s per review on average; the first took 51.2 s because it includes loading the model;
- all 3 sample answers correct, each with 3 first steps;
- lowest free memory 1.2 GB.

**Decision:**
- **Use the local model.** About 13 reviews fit in the 10-minute daily budget (600 s ÷ 44.8 s).
- **Add a memory check before loading the model**, because a daily run on a laptop with other apps open (1.6 GB free on 12 Oct) would otherwise swap. That check is part of M2.

**M2 label check (14 Oct)**: `gemma4:e2b` reviewed the 50 labeled repos with code confidence of at least 0.4. In this check Gemma saw only the README excerpt, description, topics and issue titles.

| | Precision | Recall | Reported | Time per review |
|---|---|---|---|---|
| Code only | 76% | 90% | 37 | |
| Gemma, first rule, thinking off | 80% | **52%** | 20 | 51.1 s |
| Gemma, first rule, thinking for borderline repos | 76% | 52% | 21 | 133.3 s |
| **Gemma, new rule (same cached reviews)** | **81%** | **81%** | 31 | 51.1 s |
| Gemma, prompt v3 + new rule (re-measured) | 74% | 81% | 34 | 61.5 s |
| **Gemma 4 31B on Google's API, prompt v2 + new rule (16 Oct)** | **85%** | **90%** | 33 | 85.6 s, including waits for a busy free tier |

**Gemma 4 31B (16 Oct), the hosted version's model:**
- **Fewer mistakes:** about 8, against 12 for code alone and for `e2b`. It keeps code's recall (90%) and raises precision to 85%. For comparison, Claude Opus with the skill made 5.
- **What it got right:** it rejected stackrender, django-wiki, Zero-K, anythingmcp, mycelium and the stoatchat deployment repo, and confirmed flagr.
- **What it got wrong:** it accepted modxcms/revolution and the up-banking spec repo, and rejected the f3-nation monorepo.
- **Errors:** 3 of the 50 reviews (flipt, cdnjs/api-server, trae-workbuddy-switch) failed even after retries, with 500 or 503. They kept the code's prediction.
- **It runs on Google's servers,** so the laptop's memory didn't matter (1.3 GB free at the lowest, from other apps).

- **The first rule threw out 12 real API apps.** Seven were answers like `serves_api` with style `none` (an app with an API, but "no API style"). flipt was rejected for being gRPC, though it serves REST too. The rule counted any answer other than "serves_api + rest" as disagreement and cut confidence from 1.00 to 0.20.
- **The new rule:** an app that serves an API agrees whatever style the model names, and only a clear verdict (confidence ≥ `llm_veto_confidence`, 0.7) that it's a tool, library, spam or something else lowers confidence. On the cached reviews it makes 12 mistakes, the same number as code alone: precision up from 76% to 81%, recall down from 90% to 81%. Picked over alternatives on the same 58 labels, so the gain is small and uncertain.
- **Thinking:** no more accurate and 2.6 times slower, so it stays off.
- **Memory:** Gemma used 5.5–5.9 GB (6.2 GB free before and 0.7 GB at the lowest; 7.0 and 1.1 in the second run) on a 7.8 GB laptop. `min_free_memory_gb` is 6, so reviews wait until most memory is free. On this laptop that's typically right after login, when the daily run starts.
- **Prompt v3 was worse, so it was reverted.** It defined `serves_api` more precisely, offered style `unknown`, and passed Gemma the code's measured facts (owned spec, endpoints in the README). Gemma then copied the code instead of judging: its evidence quotes became "DocScout's checks: owns an OpenAPI/Swagger spec…", and it agreed with the code's false positives. Back to prompt v2 with the new rule: 12 mistakes, like code alone, but 3 fewer wrong picks (6 instead of 9) and 3 more missed apps. For a contributor, a wrong pick wastes time; a missed one costs little.
- **Memory got worse:** during the v3 run free memory reached 0.0 GB (6.7 GB free before), so the laptop swapped. Running 11 reviews a day unattended on 7.8 GB is heavy. ⏳ Decide: fewer daily reviews, or a hosted open-weight model.

**Compared with an AI agent given a skill (14–15 Oct)** ([method](comparison/METHOD.md), [results](comparison/RESULTS.md)). The agent was Claude Opus with a skill that holds everything DocScout learned.
- **Labels:** the agent reached 88% precision and 97% recall, against DocScout's 81% / 81%.
- **One search:** the agent found 10 picks, 4 of which you'd act on, and 79 of its 81 claims were right. DocScout found 2 picks, 1 of which you'd act on, and 10 of its 20 claims were right.
- **Cost:** the agent took 2 hours and 376k tokens; DocScout took 7.5 minutes and no tokens.
- **What you want:** projects whose docs are published as pages (a docs site, or at least the README), not an API reference that appears only after installing the app. All 6 projects you'd act on have a docs site; so do 3 of the 7 you wouldn't.
- **DocScout's misses are mostly code checks:**
  - specs found only by file name, which missed 4;
  - an AI-agent skill file counted as docs;
  - bug and feature issues counted as docs requests;
  - a docs site treated as a reason not to report.

  ✅ All four fixed on 16 Oct (sections 8 and 9). On the 13 graded projects, DocScout now finds the spec of all 10 it reports, and none falls back to "check manually".
- **Round 2 (16 Oct, after the fixes; new projects, fully blind):**
  - DocScout: 4 picks, 3 of which you'd act on, with 81% of claims right; 8.5 minutes and no tokens.
  - The agent: 10 picks, 6 of which you'd act on, with 96% of claims right; 46 minutes and 324k tokens.
  - Gemma agreed with your "serves an API" grade on all 4 (2 of 4 in round 1).
  - Remaining misses:
    - a swag-generated spec shown as hand-written (✅ fixed: a `docs.go` beside the spec marks it generated);
    - API docs in a GitHub wiki not read;
    - another product's docs repo counted;
    - the only rejected pick was the unverified "no docs found" kind (✅ decided 16 Oct: no longer reported).

## 3. Success criteria

| Metric | Target | Checked in |
|---|---|---|
| Reported items that really serve an API **and** have a real docs gap | ≥ 70% | M0 (classifier), M1 (gaps) |
| Items per weekly report you'd actually act on | ≥ 5 | M1 |
| Daily run time without the LLM, on your laptop | ≤ 10 min. Measured 13 Oct: 10 repos took 11 min and 6.6 MB before the GraphQL change, then **2 min 45 s and 1.1 MB**, so about 10–12 min for 60 on this connection | M1, M3 |
| Manual starts needed | 0, including after reboots, sleep and offline days | M3 (Linux), M5 (macOS and Windows; also on battery) |
| Silent failures | 0. An expired token or repeated failures always cause a notification | M3 |
| Setup | At most 3 questions; usually 1–2 | ✅ M0 |
| Fresh install on macOS or Windows | `pipx install`, `init` and `schedule install` work first time | M5 |

## 4. Decisions made

- **Platform and output:**
  - GitHub only; Hacktoberfest isn't part of the scoring.
  - Output is a Markdown report plus desktop notifications, with a new dated file per run. Days with nothing new write no file; the finish notification just says "Nothing new today" (and can be turned off).
  - Cross-platform: Linux by the deadline, macOS and Windows after it.
- **Independent of language and framework.**
  - Checks follow open standards (OpenAPI now; GraphQL, `.proto` and AsyncAPI later) or plain-text signals.
  - Where checking code would need rules for each language (library/SDK docs), DocScout relies on **maintainers asking for help** instead.
- **API types are modules.** REST is the first; GraphQL, gRPC, event APIs and library/SDK docs come later. Each new type passes its own accuracy check before it's switched on.
- **The LLM is always on**, with local Ollama (`gemma4:e2b`) as the default. A hosted OpenAI-compatible API is one setting away.
  - The LLM decides judgment calls, but only on repos that pass the code-only health and spam checks first.
  - It can raise a repo's confidence to at most 0.8.
- **Setup:**
  - `init` asks at most 3 questions.
  - Everything else has a default; `docscout set` changes it.
  - `daily_repo_budget` is configurable (default 60).
- **Languages:** REST *prefers* your languages (ranked higher); library/SDK docs will *require* them. A profile can force either.
- **GitHub lists come from GraphQL when there's a token** (pull requests, commits, issue search, an owner's repos), asking only for the fields DocScout reads. REST stays as the fallback without a token.
- **Process:** commits at key stages; a branch per stage; [CLAUDE.md](../CLAUDE.md) keeps this plan updated with every important change.

## 5. What real data showed (checked live, 11–13 October)

| Source or query | Result | What this means |
|---|---|---|
| `topic:openapi`, active, 10–5,000★ | 735 matches; **about 5 of 25** serve an API | Mostly code generators, validators and SDKs. A weak source |
| `topic:rest-api`, same filters | 888 matches; about as low, plus spam | A weak source |
| `topic:self-hosted "rest api" in:readme` | 624 matches; **about 10 of 15** are real apps | A good source |
| [awesome-selfhosted-data](https://github.com/awesome-selfhosted/awesome-selfhosted-data) | 1,353 hand-picked apps | **The best seed.** Downloaded as one archive, because GitHub's folder listing stops at 1,000 entries |
| Issue search for docs labels plus "api" | Mostly tiny repos where owners track their own plans, bounty farms and bot dashboards | Help requests must pass the health gate |
| Help-requested route, live sample of 18 | **16 failed the gate**, 14 of them for having fewer than 20 stars | Asking for help is a strong signal, but not enough on its own |
| `label:a,b` vs `label:a OR label:b` | The comma form works; the `OR` form returns 0 | Use the comma form |
| `(openapi OR swagger) … in:title` | 73,752 junk results | One query per keyword |
| `language:python language:go` | 205 = 112 + 93 repos; the same "any of" behaviour on issues | One search covers all your languages |
| Code search for `filename:openapi.yaml` | Needs a token; 10 requests a minute; 1,000-result cap | Optional source |
| Ollama `keep_alive: 0` | Unloads the model after every request | Keep it loaded for the batch, then unload once |
| macOS `StartInterval` | Skips runs missed during sleep | Use `StartCalendarInterval` (M5) |
| Windows Task Scheduler | Won't start on battery by default | Set the battery flags explicitly (M5) |
| `pythonw` / gui-scripts | `sys.stderr` is None; child processes flash a console window | `main_bg` logs to a file; subprocesses use `CREATE_NO_WINDOW` (M5) |
| REST closed-PR list, per repo (13 Oct) | **1.5–1.9 MB**, 35–65 s on this connection: about 19 KB of JSON per pull request | Ask GraphQL for only the fields used: about 30 KB per repo |
| GraphQL, 100 PRs at once vs 50 | 12–28 s vs usually 1–5 s | Pages of 50; a second page only when the first doesn't reach back 180 days |
| REST issue search, 100 results | 230–630 KB per search (each issue's full text); 8 searches took 440 of the 646 s of a 10-repo run | GraphQL search, 50 results, fields used only. Checked: the same matches and the same first 50 |
| GitHub search on this connection | 9–17 s per issue search either way | Search time is GitHub's, not bandwidth; fewer bytes still help on a slow link |
| systemd user session | Has the desktop bus address; a notification sent from a systemd unit appeared on screen | Notifications work from scheduled runs |
| First real Gemma review (babybuddy, 13 Oct) | Right verdict, quoting the spec; 3 first steps taken from the measured gaps; 1 min 20 s with the GitHub checks | Works. But "why it matters" restated the classification, so the prompt now defines that field |
| First real `draft` | Vague, offered to fix everything, and ended with "Issue link: [Link to new issue]" | The prompt asks for the numbers, one small first PR, and no links or placeholders. The second draft quoted "97 out of 103 operations" and proposed one endpoint group |
| Claim check on babybuddy | "chore(deps): bump mkdocs-material … in /docs" by Dependabot counted as someone writing docs | PRs by bots and dependency updates no longer count (a bug since M1) |

## 6. How it fits together

```
 PROFILE (init / set)                 SOURCES                          ANALYZE (≤ daily_repo_budget)          OUTPUT
 api types · languages ──┐   ┌─────────────────────────────┐   ┌───────────────────────────────────┐   ┌────────────────────┐
 sizes · LLM             ├──▶│ awesome-selfhosted seed     │──▶│ health gate (code only)           │──▶│ rank + reasons     │
                         │   │ repo search slices          │   │ language check                    │   │ claim/requirement  │
 API TYPE MODULES        │   │ help_requested issues       │   │ classifier (per API type)         │   │ LLM first steps    │
 rest (graphql, grpc,…)──┘   │ code search (optional)      │   │ gap scoring: spec · prose · else  │   │ report + notify    │
                             └─────────────────────────────┘   └───────────────────────────────────┘   └────────────────────┘
                                         everything saved in SQLite as it finishes, so every step can resume
```

**Principles:**
- Code makes every decision that can be checked or tested; the LLM handles judgment within code-set limits.
- Every score comes with its reasons.
- Every link in the report is built by code from verified GitHub URLs.

## 7. Setup and profile ✅

`docscout init` asks **at most 3 questions**:

| Question | When it's asked |
|---|---|
| What do you want to document? | Only when more than one API type exists, so it's skipped today. A type that needs your language (library/SDK docs) adds a "which languages?" follow-up |
| Which model reviews projects: local (Ollama, Gemma) or hosted (an open-weight model through an OpenAI-compatible API) | Unless `--llm` is given. Choosing hosted adds a model name and an API key. There's no "none" since M2 |
| GitHub token | Only if none is set. It's tested with GitHub and not saved if rejected |

**Changing settings without questions:**
- `docscout set` changes any other setting: `--languages`, `--only-these-languages`, `--sizes`, `--llm`, `--model`, `--base-url`.
- `discover` (and later `run`) takes the same flags for a single run.
- Any setting given as a flag skips its question in `init`.

**Where settings live:**
- `docscout profile` shows the settings in plain sentences.
- Settings are saved to `[profile]` and `[llm]` in the user's `config.toml`; secrets go to `secrets.env`, readable only by the user.
- All other tuning lives in [default_config.toml](../docscout/settings/default_config.toml) as "advanced".

**What the profile controls:**
- `api_types` decides which API types are enabled.
- Project sizes become the search star bands and the star ranges the gate accepts:

| Size | Stars | Default |
|---|---|---|
| small | 20–200 | on |
| medium | 200–1,000 | on |
| large | 1,000–5,000 | on |
| huge | 5,000 and up | off; switch on with `--sizes` |

- Languages accept short names (`py`, `ts`, `golang`, `c#`). Repos in your languages are marked in the sample CSV now, and rank higher from M1.
- When your languages are required:
  - the searches themselves are narrowed;
  - a repo also matches when at least 25% of its code is in one of your languages, which costs one extra API call only when its main language doesn't match.

## 8. Discovery ✅

**Sources:**
1. **The curated seed:** awesome-selfhosted, refreshed weekly. It's read in memory and never extracted, and these repos start with a higher "serves an API" score.
2. **Repo search slices:** each enabled API type's queries × your star bands (plus language filters when required), always active, not archived and not forks. M1 adds a cursor that works through a few slices each day.
3. **Help requested:** open, unassigned issues with no linked PR.
   - One query per label family (`documentation,docs` or `"help wanted","good first issue"`) × keyword (`api` plus each API type's own keywords).
   - An issue counts only if it has an outreach label or was opened by someone outside the project. Bots, dependency dashboards and bounty labels are ignored.
   - ✅ (16 Oct) It must also be about docs: a docs label, or a docs word in the title ("document", "docs", "examples", "reference"…). The comparison showed "help wanted" plus "api" finding a feature request (traceroot #2579) and a bug (mycelium #279). Docs labels are matched as words, so "docker" isn't one.
   - When a maintainer has labeled an issue "help wanted" or "good first issue", the activity check is looser (1 committer, no merged outside PRs needed).
4. **Code search for definition files** (optional, needs a token): each API type's `definition_filenames`, sliced by file size.

**Health gate (code only):**
- Not archived, not a fork, has a license, within your star ranges, and pushed in the last 60 days.
- At least 2 human committers in the last 90 days.
- At least 1 merged pull request from an outside contributor in the last 180 days.

Checks run cheapest first, so rejected repos cost few API calls.

**Classifier (text and file names only):**
- **Role evidence:** app words count for the repo, tool and library words against it; Docker or compose files count for it; spam is dropped.
- **Each enabled API type adds its own evidence.** For REST: a REST mention in the description, an owned OpenAPI spec, endpoints in the README, and help-request issues about OpenAPI, Swagger or endpoints.
- **Output:** the best type, its confidence, and the confidence for each type.

## 9. Analysis and scoring (M1)

**Health score** (shown in the report):
```
health = 0.35·min(1, outsider_merged_180d/5) + 0.20·outsider_merge_rate + 0.15·ttm_score
       + 0.20·min(1, human_committers_90d/5) + 0.10·has_contributing
```

**Gap score, 0–100 (higher = worse docs):**
- **A. Spec with gaps.** It uses the worst *owned* spec, meaning not vendored, a test or an example, and with at least 3 operations. Each check below scores the share of operations failing it, multiplied by its weight:

  | Check | Weight |
  |---|---|
  | No summary or description | 20 |
  | Parameters without descriptions | 15 |
  | No examples | 15 |
  | No 2xx schema | 10 |
  | No error responses | 10 |
  | `info.description` under 50 characters | 10 |
  | Security schemes undescribed | 10 |
  | Tags undescribed | 5 |
  | No servers | 5 |

  - `$ref` is resolved only within the file.
  - **Finding the spec** ✅ (16 Oct): files named `openapi*`/`swagger*` first, then any YAML or JSON in an `openapi`/`swagger` folder, then files named like `api.yaml` or `public-api.yaml`, at most 4 fetched. The parser drops files that aren't specs. Matching by name alone missed 4 specs in the comparison (dagu, jupyter_server, traceroot, ChurchCRM). The classifier's "owns a spec" evidence still uses names only, so the measured label numbers stay valid.
  - **Generated specs** (a `DO NOT EDIT` header, or CI that regenerates the file) keep their score, but the suggestion becomes "edit the code annotations".
- **C. Docs only in prose.** Each endpoint in the README or docs is checked for: a description (25), a request example (20), a response example (25), status or error codes (15) and auth (15). If the docs are at least 80% complete, the gap is set to 35 and the suggestion becomes "turn them into an OpenAPI spec".
- **D. No docs found.** ✅ **No longer reported** (decided 16 Oct). It rested only on not finding docs, never on reading them. In the comparison, the one such pick (VoucherVault) had its API docs in a GitHub wiki, and the author wouldn't act on it. Before that it scored 60, and only with type confidence of at least 0.8.
- **Docs elsewhere or generated at runtime.** Detected from:
  - the homepage;
  - a docs link in the README, which only counts if its address mentions the project or its owner (so `laravel.com/docs` doesn't), one entry per site;
  - a sibling `*docs*` or `*website*` repo;
  - a Swagger UI, ReDoc or `openapi.json` mention, or `/docs` on a local address (`localhost:8000/docs`).

  Prose gaps with these signs are capped at 50 and marked "check manually" until M4. With no endpoints in the repo at all, the gap is **40** ("docs probably elsewhere").

  **These items are reported only when maintainers asked for help** ✅ (13 Oct). In the first daily report, 4 of the 10 items were "docs probably elsewhere" guesses, while projects like docassemble and kuzzle have documentation websites. A help request says the docs need work wherever they live.
- **Signals must belong to this project** ✅ (13 Oct, after wrong signals in the first daily report):
  - a docs link counts only if its address contains the full repo or owner name (django-crm had counted Django's own docs);
  - a named docs repo must name the project (`mylar3-website`), and a generic one (`docs`, `website`) counts only when the owner is one product (`kuzzleio/documentation`) or has at most 10 repos (OFBiz had got `apache/tvm-site` and `apache/airflow-site`);
  - Markdown files under decision-record, audit, proposal, design or internal folders aren't read as API docs (kuzzle's `docs/adr-001/step-15-audit/A3-api.md`);
  - ✅ (16 Oct) neither are files in hidden folders (`.agents/`, `.claude/`, `.cursor/`), which hold instructions for AI coding agents (ChurchCRM's `.agents/skills/churchcrm/api-development.md`).
- **Docs published as pages** ✅ (16 Oct): any of:
  - a docs-site config in the repo (MkDocs, Read the Docs, Sphinx, Docusaurus, mdBook, Mintlify, Antora, VitePress);
  - a docs host as the homepage (`docs.*`, `*.readthedocs.io`);
  - a README docs link whose host carries the project's or owner's name (badges and package registries don't count);
  - a separate docs repo;
  - Markdown API docs on GitHub.

  These add `[scoring] published_docs_bonus` (10) and a "Docs published" line, because the writer prefers projects whose docs can be read without installing them (comparison grading, 16 Oct). It's a bonus, not a filter: 5 of the 7 graded "no"s have published docs too.
- **Generated-spec limitation:** detection reads the file's header and folder names, and, since 16 Oct, the files beside it: swag's `docs.go` next to `swagger.json` marks the spec generated (autentico). Specs exported by a framework without any marker (drf-spectacular, as at modoboa) still show as hand-written.

**Live findings from 12 Oct, already fixed:**
- **"specification" is no longer a tool word,** since it misclassified zot, an OCI registry with a Swagger spec.
- **Many topics count as spam only on new repos.**
- **Spam is re-checked once full repo details are fetched.**
- **Curated repos outside your star range are dropped without an API call.**
- **The daily budget counts repos that actually used the GitHub API.**

```
score = gap × (0.5 + 0.5·health) × type_confidence + issue_bonus (help wanted +10, good first issue +5, docs label +5; max +15)
        + language bonus when the repo is in one of your preferred languages (M1)
        + published-docs bonus (10) when the docs are published as pages (16 Oct)
```

**Effort** is counted in operations or endpoints needing work: up to 10 is S, up to 40 is M, more is L.

## 10. Before you contribute (M1; top 10 only, about 3 API calls each)

- **Already claimed?** Checks open PRs that touch docs or the spec, and phrases like "I'll take this" in the issue's comments. PRs by bots and dependency updates don't count (13 Oct).
- **Requirements, shown only when found.** They never change a repo's score, and each quotes the sentence it matched:
  - a **CLA** to sign;
  - a **DCO sign-off** on every commit;
  - an **AI-contribution policy**, matched only on whole-word phrases near contribution words.
- **Local setup**, for information only: easy (Docker, compose or a devcontainer) / documented / unclear.

## 11. The LLM (M2)

**Gemma is required** (decided 13 Oct, for the challenge's "the open pieces should be what makes your project work"):
- ✅ **It reviews every repo that passes the health checks** with confidence of at least 0.4, up to `[llm] reviews_per_run` a day (11: about 10 minutes at the measured 51 s each). Most promising first: before its review, a finding is ranked by the score it would get if the model agrees.
- ✅ **Only reviewed repos are reported.** If Gemma can't run (Ollama not running, memory low), findings are held, not dropped. A later check the same day reviews them once memory is free; otherwise the next run does. Held findings wait up to 14 days. If Gemma can't run for 2 days in a row, you get a "needs attention" notification.
- ✅ **`init` no longer offers "none":** the choice is local Gemma or a hosted open-weight model. `run --no-llm` is gone, and `score owner/repo` includes the model's review.

**Jobs:**
1. **Judge** whether the project really has an API worth documenting (the code classifier is 76% precise: apps that only mention "API" get through, and borderline repos are dropped unseen). Gemma's verdict, API style and a quoted piece of evidence adjust confidence within the limits below.
2. **Guide:** why its docs matter, and up to 3 first steps based on the gaps code found.
3. ✅ **`docscout draft owner/repo`** (on demand, after you pick a project): a short first message asking the maintainers whether a docs PR is welcome, using the current issue and PR state. DocScout never posts anything itself. It replies on an open "help wanted" or docs issue when there is one, otherwise it drafts a new issue. The claim check runs again first and warns if someone has started, and CLA or AI-policy notes are shown. The draft is printed with control characters removed.

**Thinking:** Gemma 4 supports it (on by default in the model; DocScout turns it off). ✅ Measured (section 2): no more accurate, 2.6 times slower, so `think = "off"`. The setting stays for faster machines and hosted models.

**Not built** (to keep the scope small, decided 13 Oct): a weekly report and a `picks` command. Reports stay one per run, and `latest.md` is the newest.

**Review schema:** `{project_type, api_style, confidence, evidence, why, first_steps}`.
- The API type decides whether the LLM agrees with it. For example, a REST check plus an LLM answer of "GraphQL" counts as disagreement.
- Disagreement lowers confidence in proportion to the LLM's certainty.
- Agreement can raise confidence to at most 0.8.
- The LLM never sees repos that failed the gate.

**Backends:** both done ✅.
- Ollama: JSON schema output, `think: false`, the model kept loaded during the batch, then unloaded.
- Any OpenAI-compatible API, falling back to JSON mode if a provider doesn't support schemas.

- ✅ **Memory check:** a local model loads only when `[llm] min_free_memory_gb` (6, measured: Gemma used 5.5–5.9 GB) is free. A run started on a busy laptop holds its findings, and the next 15-minute check reviews them without a new run until memory is free. The value is set from the label check's memory measurement.
- ✅ **What the report shows:** Gemma's verdict with its evidence quote and the confidence change (e.g. 0.50 → 0.80), why the docs matter, and numbered first steps. Everything the model writes is escaped like other untrusted text. A project the model can't give a valid answer for in 2 runs is dropped.

**M2 tuning:** `bench-llm` recommends `reviews_per_run` (about 13 on this laptop, at 44.8 s per review). ✅ Built: `docscout eval tests/fixtures/labeled_repos.csv --llm [--think off|borderline|on]` reviews the 50 labeled repos with code confidence of at least 0.4 (about 37 minutes at 45 s each), using the repo data `--reclassify` cached, so it makes no GitHub calls. Reviews are cached per repo, model and thinking setting, so a thinking comparison only reviews the borderline repos again. It reports precision and recall with and without the model, seconds per review, and the memory used, with a suggested `min_free_memory_gb`. In this check the model doesn't see the docs gaps, which a daily run gives it. ⏳ To run with other apps closed. **The label check is required, not optional:** precision and recall on the 58 labeled repos, with and without Gemma, become the evidence in the DEV post. If Gemma doesn't help, the prompt is tuned first.

## 12. Security

- **Network:** until M4, the tool only contacts the GitHub API, plus your LLM.
- **M4's safe fetcher:**
  - is a client separate from the GitHub one, so the token can't leak;
  - only fetches http(s) on ports 80 and 443;
  - rejects any non-public IP, checking again after every redirect;
  - has a total deadline and caps on bytes.
- **Parsing:**
  - YAML aliases are rejected, which blocks memory-bomb files ✅;
  - specs are capped at 2 MB;
  - archives are read in memory, never extracted ✅;
  - `$ref` resolution stays within the file.
- **The report:**
  - all untrusted text is escaped;
  - HTML, bidirectional-text and ANSI control characters are stripped;
  - links come only from validated `https://github.com/` URLs;
  - README text reaches the LLM inside delimiters ✅.
- **Notifications** use fixed text, with values passed as arguments, never inserted into scripts.
- **Lock:** an OS file lock, released automatically if the process crashes.
- **Secrets:**
  - a fine-grained, public read-only token;
  - stored in `secrets.env` with mode 600 ✅;
  - environment variables take precedence;
  - never logged.

## 13. The report (M1)

`reports/2026-10-14.md`. A second run that day writes `…_2.md`, and `latest.md` is a copy of the newest.

```markdown
# DocScout · 14 Oct 2026 · 6 new · 2 still open
### 1. example-org/uptime-api · score 78 · effort M
★ 412 · Go (yours) · pushed 2 days ago · outside PRs: 9 merged / 83% merge rate / median 4 days to merge
**Spec with gaps:** [`api/openapi.yaml` @ a1b2c3d](permalink) (OpenAPI 3.1, 38 operations, hand-written)
- 21/38 operations have no description (e.g. `POST /checks`, `GET /checks/{id}/results`, +19)
- No request/response examples · No 4xx responses
**Maintainers asked for help:** [#214 Document webhook payloads](…) (help wanted, unassigned, not claimed)
**Before you start:** ✅ not claimed · ⚠️ CLA required ("All contributors must sign…") · local setup: easy (docker-compose)
**First steps (LLM):** …
Score: gap 72 × health 0.90 × type 0.95 + bonus 10
```

**Quiet days ✅:**
- Nothing new: no file is written. With finish notifications on, it says "Nothing new today"; `docscout status` shows the day's runs.
- Earlier items still open appear under "Still open from earlier" in the next report. Re-checking them for changes (someone else fixed the docs, a PR was merged) is in section 19.
- After 7 days in a row with nothing new, one notification suggests a wider search (`docscout set --sizes …`).
- Findings that didn't fit in a report (`max_items`), or whose run was cut off before writing it, go into the next report for up to 14 days.

**Problem alerts ✅:** no token, a rejected token (401), broken settings, or 3 failed runs in a row send a "DocScout needs attention" notification, at most once a day each. These can't be turned off.

## 14. Running unattended

| Situation | Behavior |
|---|---|
| Every 15 minutes | `run --if-due` exits in under 1 second unless a run is due **and** the machine is online ✅ |
| When a run is due | Today's runs (yours and scheduled ones) have checked fewer than `daily_repo_budget` repos, and no scheduled run today ran out of candidates. "Today" is your local day ✅ |
| Online check | One `GET /rate_limit` with a 10 s timeout and no retries; free. A 401 sends an alert instead of starting a run ✅ |
| Offline | Logs it and exits; the run stays due and starts at most 15 minutes after reconnecting ✅ |
| Connection lost mid-run | The run stops as "partial" without marking the remaining repos as checked; the next check continues it ✅ |
| Shut down or killed mid-run | Progress and findings are saved as they happen and the OS releases the lock. The next check marks the run "cut off", continues it, and reports its findings ✅. SIGTERM (shutdown) ends a run like Ctrl+C |
| Rate limited | Waits for the reset time; if that's more than 15 minutes, stops and continues after the reset ✅ |
| Failed run | The next try waits an hour; at most 8 scheduled runs a day ✅ |
| Another run in progress | The file lock makes the new one exit quietly; a manual `docscout run` says so ✅ |
| LLM unavailable | The report uses code-based results and says "LLM review skipped" (M2) |

`docscout schedule install|uninstall|status [--dry-run]`:
- **Linux (M3) ✅:** a systemd user service and timer in `~/.config/systemd/user/`: `OnStartupSec=2min`, `OnCalendar=*:0/15`, `Persistent=true`, `Nice=10`, `IOSchedulingClass=idle`, `TimeoutStartSec=2h`. It starts this installation's Python with `-m docscout run --if-due`, and runs while you're logged in (no lingering, since notifications need your desktop session). `schedule status` warns when the timer is stopped, when the Python it starts no longer exists, or when the last check failed; `install` sends a test notification.
- **macOS (M5, after the deadline):** a LaunchAgent with `RunAtLoad` plus `StartCalendarInterval` at minutes 0/15/30/45, so runs missed during sleep happen on wake. Loaded with `launchctl bootstrap gui/<uid>`, with absolute paths.
- **Windows (M5, after the deadline):** Task Scheduler XML with one repeating 15-minute `TimeTrigger`, plus:
  - `StartWhenAvailable=true`;
  - `DisallowStartIfOnBatteries=false` and `StopIfGoingOnBatteries=false`;
  - `MultipleInstancesPolicy=IgnoreNew` and `InteractiveToken`.

  It runs the windowless `docscout-bg` entry point, and every subprocess uses `CREATE_NO_WINDOW`.

## 15. Data model (SQLite, versioned with `PRAGMA user_version`; version 3 since M2)

As built ✅:
- `repos(key PK, full_name, source, stars, language, api_type, type_conf, health, rejected, status[new|reported|ignored|done], status_reason, first_seen, last_checked, last_reported)`
- `findings(id, run_id, repo_key, api_type, kind, gap, score, effort, details JSON, created, review[NULL waiting|accepted|rejected|error])`: the PR stats, issues, before-you-start checks and the model's review live in `details`
- `runs(id, started, finished, status[running|ok|empty|partial|failed], analyzed, new_items, api_calls, report_path, error, run_limit, started_by[you|schedule], resume_after)`: `analyzed` is saved as the run goes; `reviewed` (M2) counts the day's reviews
- `sweep(slice_key PK, page, cycle, last_used)`: the repo-search cursor
- `state(key PK, value, updated)`: the last scheduled check, alerts sent today, failures in a row, days without anything new

The model's reviews are stored in `findings.details`, so no separate `llm_reviews` table was needed.

## 16. Code layout

✅ = exists today. Grouped by stage on 16 Oct (28 loose modules had made the package hard to explore); the code didn't change, only where it lives.
```
hacktoberfest/
  pyproject.toml ✅  LICENSE ✅  README.md ✅  CLAUDE.md ✅  render.yaml ✅  deploy/render.toml ✅  .github/workflows/ci.yml (M5)
  docs/ PLAN.md ✅  comparison/ METHOD.md ✅ RESULTS.md ✅ skill/SKILL.md ✅
  docscout/
    cli.py ✅  __main__.py ✅  errors.py ✅      # init set profile run status schedule draft done ignore score discover eval bench-llm
    settings/ config.py ✅ profile.py ✅ languages.py ✅ setup_wizard.py ✅ default_config.toml ✅
    find/     discover.py ✅ github.py ✅ health.py ✅ classify.py ✅ evidence.py ✅
              sources/ awesome_selfhosted ✅ repo_search ✅ help_requested ✅ code_search ✅
    analyze/  tree.py ✅ gaps.py ✅ elsewhere.py ✅ checks.py ✅ scoring.py ✅ safe_yaml.py ✅
              apitypes/ base.py ✅ rest.py ✅ openapi.py ✅ rest_prose.py ✅     # graphql.py, grpc.py, … (later)
    llm/      base.py ✅ ollama.py ✅ openai_compat.py ✅ memory.py ✅ review.py ✅ draft.py ✅
    run/      pipeline.py ✅ daily.py ✅ db.py ✅ lock.py ✅ notify.py ✅ report.py ✅ sanitize.py ✅
              scheduler/ __init__.py ✅ linux.py ✅ · macos.py · windows.py (M5)
    measure/  evaluate.py ✅ reclassify.py ✅ llm_eval.py ✅ bench.py ✅
    hosted/   picks.py ✅ atlas.py ✅ billing.py ✅ web.py ✅ job.py ✅ templates/index.html ✅ (section 20)
    (M4: find/safe_fetch.py)
  tests/ ✅ 200 tests (186 and 1 skipped without the `hosted` extras) · fixtures/specs, fixtures/readmes, fixtures/labeled_repos.csv ✅
```

## 17. Risks

| Risk | Mitigation |
|---|---|
| **Deadline (one week; target Thu 15)** | M3 before M2; "if time allows" items cut first; M4 and M5 after the deadline |
| Discovery accuracy is low (**confirmed** for topic search) | Curated seed, per-source accuracy check in M0, classifier, health gate |
| Noisy help requests (**confirmed**) | Outreach-label or outside-author rule, deny lists, health gate |
| The local LLM is too slow on 7.6 GB of RAM (1.6 GB free on 12 Oct; the model is 4.6 GB) | `bench-llm` with apps closed; hosted or `none` as fallback; every LLM setup problem is reported with its fix, and the report works without the LLM ✅ |
| A temporary GitHub error ends a long run (**seen** on 12 Oct: one 404 crashed `discover`) | One retry on short-lived 404s; a failing repo is skipped and recorded; Ctrl+C keeps partial results ✅ |
| A PR edits a generated spec | Generated-spec check redirects the suggestion to code annotations |
| Wasted effort (already claimed, CLA, AI policy) | Claim check and requirement badges on the top 10 |
| The small local model isn't a better judge than the code (**measured** 14 Oct) | Agreement rule fixed (52% → 81% recall); measured facts in the prompt; Gemma's clearest value is writing why the docs matter, first steps and drafts. A larger hosted open-weight model is one setting away |
| Prompt injection pushes a repo up the ranking | Confidence raise capped at 0.8; code-only gates; sanitized output |
| A malicious repo targets your machine | Alias-free YAML, in-memory archives, fixed notification text, sanitized report, safe fetcher (M4) |
| The token expires and runs fail silently | Alerts for a missing or rejected token, broken settings and 3 failed runs in a row ✅ |
| A slow connection makes the daily run long (**seen** 13 Oct) | GraphQL lists with only the fields used ✅; low CPU and disk priority ✅; the start notification gives the expected time, learned from earlier runs ✅ |
| Code changes while the daily runs use this folder (editable install) | M2 is built in a separate git worktree; this folder stays on tested code |
| macOS/Windows scheduler quirks (**confirmed**) | Settings in section 14, `--dry-run` tests, a real test on both (M5) |

## 18. Verification per stage

- **M0:**
  - `discover --sample 60`, you label, then `eval` shows at least 70% overall and the accuracy per source;
  - `bench-llm` reports seconds per review and peak memory.
  - ✅ 81 tests pass.
- **M1:**
  - `docscout score` on fixtures: a bare spec scores high with reasons, a vendored spec is skipped, a `DO NOT EDIT` spec suggests editing annotations;
  - `run --no-llm --limit 10` shows a score breakdown, permalink and badges for every item, with no one-person repos, API tools or bounty farms;
  - you'd act on at least 3 of the top 10.
- **M2:**
  - an injected README ends at no more than 0.8 confidence;
  - a repo that fails the gate never reaches the LLM;
  - a "code generator" verdict drops the repo;
  - `provider = "none"` still gives a full report;
  - you rate at least 7 of 10 first steps as useful.
- **M3:**
  - ✅ offline: logs it, then runs once you reconnect; a connection lost mid-run pauses it without skipping repos;
  - ✅ a cut-off run is continued and its findings reported; `kill -9` doesn't leave runs blocked (tested with a real killed process);
  - ✅ a rejected or missing token sends one alert a day; 3 failures in a row send one;
  - ✅ a quiet day writes no file; 7 quiet days send one hint;
  - ✅ the units and a test notification work through this laptop's systemd user session;
  - ⏳ the unattended test: 2 days from `schedule install` with no manual starts, including a reboot and an offline period.
- **M5:** a fresh `pipx` install on a Mac and a Windows machine works, including on battery and after sleep; CI is green on 3 operating systems.

## 19. Later (after M5)

Re-checking still-open items for changes (docs fixed by someone else, a PR merged); pre-contribution message drafts; learning from merged or rejected PRs; running the LLM only when plugged in or idle; new API types (GraphQL, gRPC, AsyncAPI, OpenRPC, library/SDK docs via help requests); Up For Grabs as a seed; GitLab and Codeberg; a dashboard; Spectral lint; standalone executables.

## 20. Hosted version (16 Oct)

For writers who'd rather not run anything: no terminal, and no 6 GB of free memory, which Gemma pushed this laptop to its limit for in every comparison run. It also serves the challenge's "something someone would actually pay for".

**Built on branch `hosted`:**
- **Daily job** (`docscout.hosted.job`, a Render cron job): load DocScout's database from Atlas, `docscout run` with [deploy/render.toml](../deploy/render.toml), publish the picks from the last 7 days, save the database back. The save also happens after a failed run.
- **Model:** Gemma 4 31B (`gemma-4-31b-it`) through Google's OpenAI-compatible Gemini API endpoint, on the free tier. Google lists `gemma-4-31b-it` and `gemma-4-26b-a4b-it` for the key. Under load it answered 500 or 503 to about half the requests (16 Oct), so busy answers (429, 5xx) are retried after 5, 20 and 60 s, or after the provider's `Retry-After`. Only schema mode returned clean JSON; JSON mode on the 26B returned its "thoughts".
- **MongoDB Atlas** (free tier):
  - DocScout's SQLite file, in GridFS, newest 3 versions kept. Render cron jobs can't keep files or attach disks;
  - the picks: one document, rewritten after each run;
  - subscriptions: no names or email addresses kept.
- **Website** (`docscout.hosted.web`, Starlette and Jinja2, a Render web service). Redesigned on 16 Oct after "a wall of text": a short welcome, 3 how-it-works steps, cards with labels (language, stars, effort, docs published, help requested, not claimed, outside PRs merged), "What needs doing" and Gemma's note up front, the details folded away (`<details>`, no JavaScript):
  - the picks from the last 7 days: every project first reported in that window and still open, best score first. Each stays for 7 daily runs; a reported project isn't checked again, so it doesn't come back;
  - the top 3 free (5 until 17 Oct), the rest after a Stripe Checkout subscription;
  - subscribers can switch to newest first (17 Oct): the day it was found, then best score. Every card says when it was found, and a "New" label marks the last 24 hours;
  - the paywall is enforced on the server, so the page holds only what the visitor may see;
  - subscribers page through the list, 10 picks a page (server-side pages: infinite scrolling would need JavaScript);
  - the page states Gemma's role plainly: it reviews every candidate and turns away the ones that aren't real apps with an API, which raised precision from 76% to 85%.
  - no JavaScript, and a Content-Security-Policy that allows no scripts;
  - text escaped, and links only to GitHub URLs DocScout trusts.
- **Subscriber pass:** an HMAC-signed, HttpOnly cookie for 31 days, issued only after Stripe confirms the session is complete and paid.

**Decisions:**
- **Render, not DigitalOcean.** The $50 Hacktoberfest credit covers it. DigitalOcean's cheapest fit was about $48 a month, and signing up asked for more than the plan. On Render:
  - the cron job is the agent's runtime ("your project's AI runtime");
  - the website is "an agent's front end".
- **Google AI Studio for Gemma.** It's free with no card, and it's Google serving Gemma. DigitalOcean's Inference also serves Gemma 4 ($0.18 / $0.50 per million input / output tokens), but the account wanted a charge. OpenRouter (`google/gemma-4-31b-it:free`) is the fallback: one setting.
- **Price: $3 a month, not weekly.** Card fees (about $0.30 plus about 3% per charge) leave about $2.60 of $3, and weekly billing would pay the fixed fee four times.
- **3 free picks** (17 Oct; it was 5). Render's first runs found 3 picks per 60 repos, so with a list of 10–20, 5 free would have given away a quarter to half of it. A writer needs only one project at a time. The free 3 are the top scores at that moment, so they change when better picks arrive.
- **Bigger runs on Render** (17 Oct): up to 200 repos, 30 reviews and 30 new picks a run ([deploy/render.toml](../deploy/render.toml)). The defaults (60, 11, 10) were set for a laptop's memory and time. They're caps: Gemma only reviews the projects that pass the code checks, and the new-picks cap equals the review cap, so every accepted project is published the same day.

**Cost:**
- Render: a cron job (billed per second, $1 minimum a month) plus the web service. Use the paid plan during judging so visitors don't wait about a minute for a sleeping free service; switch to free after.
- Gemma and Atlas: $0 on the free tiers.

**Prize categories it genuinely uses:** Render, Gemma and MongoDB Atlas. The .tech domain category was dropped: the promo code was no longer available (16 Oct).

**Rehearsal (16 Oct), on this laptop against the real Atlas and Stripe test mode:** 42 picks published; 5 shown free; Checkout opened and the test card paid; the return link unlocked all 42. Atlas recorded the subscription with Stripe's IDs only (no email).

**First runs on Render** (60 repos each, before the bigger runs):

| Run | Checked | Reviewed by Gemma, all accepted | Time | GitHub requests |
|---|---|---|---|---|
| 16 Oct, 23:08 UTC (started by hand) | 60 | 3 | 6 min | 197 |
| 17 Oct, 04:15 UTC (scheduled) | 60 | 3 | 7 min | 216 |

In the first run, 16 of the 60 passed the health checks. Render started with an empty memory. The rehearsal had published picks from a database on this laptop without saving that database to Atlas, so Render's first run replaced the 42 rehearsal picks with its own 3.

**⏳ Still to do:**
- ✅ Gemma 4 31B on the 58 labels: 85% precision, 90% recall (section 2);
- ✅ deployed: the public GitHub repo, the Render Blueprint, Atlas access for Render;
- a real end-to-end test payment on the live site, in test mode;
- after the deadline: check published projects again after 90 days, like the others, so one that still has the gap and isn't claimed can come back.
