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
| **Hosted version** (branch `hosted`) | ✅ Built (16 Oct), section 20: a website that shows the picks from the last 7 days, the top 3 free and the rest for $2 a month (Stripe Checkout, test mode); a daily Render cron job running DocScout with Gemma 4 31B on Google's API; MongoDB Atlas for DocScout's memory, the picks and the subscriptions. ✅ Gemma 4 31B measured on the 58 labels: 85% / 90%, against 81% / 81% for `e2b` (section 2). ✅ Deployed (16–17 Oct): the code is public on GitHub, and the daily job runs on Render (on schedule since 17 Oct, 04:15 UTC). ⏳ A test payment on the live site | | Fri 16 – Sat 17 Oct |
| Challenge submission | Demo video; a real docs contribution made with a DocScout pick (the "first user"); the DEV post, written in your own voice | | Fri 16 – Sun 18 Oct |
| **Deadline** | | | **Mon 19 Oct** |
| **M4. Read external docs** | | **After the deadline** | |
| **M5. macOS and Windows support** | launchd and Task Scheduler setup, notifications and file lock on both, CI on 3 operating systems, `pipx` packaging, a fresh-install test on real machines | **After the deadline** | |
| **M6. Open picks stay listed, and stay true** | Planned 6 Nov (section 21), after the website's list fell to 9: open picks listed with no age limit; a look for changes at every listed pick every 6 hours (one request per 60 picks); the gap measured again when its docs change, health every 7 days; claims per gap, with open PRs measured instead of judged; Gemma checks that each help request asks for the measured work; bounty programs filtered. ✅ Steps 6a–6d built and passed (6–7 Nov), deployed 6 Nov. 6e: ✅ README, public skill and plan (7 Nov); ⏳ 3 days of runs; ⏳ the next 10 new help requests labeled | | After the deadline: steps 6a–6e |

**If the schedule slips:** the "if time allows" items go first, then M2 shrinks to first steps only. M1's must-ship items stay, because without them the tool can't tell you what to fix.

**macOS and Windows are planned, not dropped.** Everything built so far is already plain cross-platform Python:
- user folders come from `platformdirs`;
- the secrets file is created private on Unix, and the permission call is skipped on Windows;
- the windowless `docscout-bg` entry point exists.

M3 builds scheduling behind a small per-OS interface (`scheduler/linux.py`), so M5 only adds `macos.py` and `windows.py`. Their exact settings are already worked out (section 14).

**How work is saved:** `main` holds finished work. Each stage gets its own branch (`m1-report`, `m2-llm`, …), merged into `main` when its exit check passes. Since 8 Nov, changes are left uncommitted for you to inspect locally, and committed only when you ask (until then, Claude committed at each key stage); always with tests passing, and never with secrets or local samples.

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
- **The skill is public** (17 Oct): [skills/find-api-docs-to-contribute/SKILL.md](../skills/find-api-docs-to-contribute/SKILL.md), for writers who'd rather use their own agent (Claude Code or any tool that supports Agent Skills); the README says how to install it.
  - It adds what DocScout learned after the comparison: the size cutoff, the claim rules Gemma follows, help requests that must be about the API docs, install commands and hidden agent folders that aren't docs, GitHub wikis, another product's docs repo, swag's `docs.go`, comparing documented endpoints with the routes in the code, and never recommending a project only because no docs were found.
  - It uses `gh api` or a token instead of the comparison's `ghapi` wrapper, and its frontmatter keeps to the fields other tools accept (`name`, `description`, `license`, `compatibility`).
  - The comparison's copy ([comparison/skill/SKILL.md](comparison/skill/SKILL.md)) stays as it was tested, so the results can be repeated.
- **Round 3 (17 Oct, both sides updated; [results](comparison/RESULTS.md#round-3-17-oct-both-sides-updated)):**
  - **DocScout's fixed 60-repo run found nothing.** 10 of its 13 healthy projects have a project website that may hold their docs, which it can't read yet (M4).
  - **An extra run to 200 repos found 3 picks:** you'd act on 1, maybe 2, with 83% of claims right.
  - **The agent with the public skill found 10:** you'd act on 4, maybe 3, with 95% of claims right. It took 1 h 20 min and 361,000 tokens, against about 20 minutes and no tokens.
  - **The public skill ran end to end** without problems, and listed what it found unclear.
  - **Fixed the same day** ✅, each checked on the round 3 project it came from:
    - **outsiders** exclude anyone who merged a PR in the repo, and bot accounts named like users (`*-bot`, `*-robot`). zowe's "63 outside PRs" were maintainers with private org membership and `zowe-robot`; now it's 1, as the fact-check found;
    - **`$ref`s to percent-encoded path names** are followed: sharry has 62 operations, not 57, and 4 with undescribed parameters, not 2;
    - **AI policies** are looked for with links removed and whole words only: free-llm-api-hub's contributors badge (its name contains "llm") was quoted as one. Its real heading, "AI-assisted contributions are welcome", is found now;
    - **docs links keep their path**: eikek.github.io/sharry, not the bare host, which returns 404;
    - **the public skill**: what the agent found unclear (outsiders, paging commits, AI co-authors, secondary rate limits, star lookups for help requests, what counts as an example, 204s, encoded `$ref`s, uncommitted specs, error sections, deprecated endpoints, maintainers' own PRs, the PR branch), plus the writer's grades: don't recommend API docs readable only in the running app, and measure the page readers see.
  - **After the deadline (⏳):** endpoints written without an HTTP method (`/api/v1/no-card.json`) and endpoint tables in sub-folder READMEs aren't found; local setup should read CONTRIBUTING's commands; check that the published API page is built from the spec that's measured (sharry's isn't).

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
- **Process:** changes left uncommitted for you to inspect, and committed when you ask (since 8 Nov; commits at key stages before that); a branch per stage; [CLAUDE.md](../CLAUDE.md) keeps this plan updated with every important change.

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
| Code search for `filename:openapi.yaml` | Needs a token; 10 requests a minute; 1,000-result cap. Rechecked 10 Nov: each of the 16 queries (4 file names × 4 size bands) has 6,000–42,000 results; the first pages gave 1,436 repos new to DocScout, of which 191 pass the cheap checks (672 have under 20 stars, 352 no licence, 215 no push in 60 days) | On the website since 10 Nov. Results carry no stars, so each page's repos are looked up together in one GraphQL request. No search can be paged past 1,000 results (page 11: "Cannot access beyond the first 1000 results"), there's no cursor, and GraphQL can't search code, so bands with more than 1,000 are split by file size, to the byte (`size:1000..1100`: 942 `openapi.yaml` files) |
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
   - An issue counts only if it has an outreach label or was opened by someone outside the project. Bots, dependency dashboards, bounty labels and (since 6 Nov) bounty programs such as Stellar Wave, whose issues collect applications for points, are ignored.
   - ✅ (16 Oct) It must also be about docs: a docs label, or a docs word in the title ("document", "docs", "examples", "reference"…). The comparison showed "help wanted" plus "api" finding a feature request (traceroot #2579) and a bug (mycelium #279). Docs labels are matched as words, so "docker" isn't one.
   - When a maintainer has labeled an issue "help wanted" or "good first issue", the activity check is looser (1 committer, no merged outside PRs needed).
4. **Code search for definition files** (needs a token; on the website since 10 Nov): each API type's `definition_filenames`, sliced by file size, so 16 queries for REST. **Every result is reached** (10 Nov): no search can be paged past its first 1,000 results, and each of the 16 had 6,000–42,000 (about 380,000 in all), so a band with more than 1,000 is split in two by file size, and again, until each can be read to its end (`openapi.yaml` under 5 KB took 7 splits, down to 0–39 bytes with 371 results). Each split costs one search request. The bands are a queue kept in DocScout's memory (`state`), the largest files first: runs work through it in order, `code_search_per_run` (8) bands a run, a band being read stays at the front until it's finished, and a finished band goes to the back, so after the last one the search starts over; each band continues from the page it reached. Results shifting between pages (new files, deleted ones) cost at most a repeat, which is skipped for free, or a miss until the band's next turn. Changing the file names or size bands in the settings starts the queue again. Code search returns only a few repo fields, without stars, and most repos it finds are small or unlicensed, so each page's repos are looked up together, 50 to a GraphQL request (stars, licence, archived, fork, last push), and those failing the cheap checks are turned away without fetching each repo or counting toward `daily_repo_budget`. When GitHub can't answer a look-up, those repos are fetched one by one, as before.

**Health gate (code only):**
- Not archived, not a fork, has a license, within your star ranges, and pushed in the last 60 days.
- At least 2 human committers in the last 90 days.
- At least 1 merged pull request from an outside contributor in the last 180 days. Outside means not OWNER, MEMBER or COLLABORATOR, and (since 17 Oct) not anyone who merged a PR in the repo, nor a bot account named like a user.

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
- **A. Spec with gaps.** It uses the worst *owned* spec, meaning not vendored, a test or an example, and with at least 3 operations. Each check below scores the share failing it (of the operations it applies to, or of the fields), multiplied by its weight. Since 6 Nov (M6 step 6c, section 21):

  | Check | Weight |
  |---|---|
  | No summary or description | 20 |
  | Parameters without descriptions | 10 (15 until 6 Nov) |
  | Fields without descriptions: every field a reader sends or gets back, each once | 10 (new) |
  | No request example, of the operations that take a request body | 7 |
  | No example of a successful response, of the operations that return something | 8 (with the line above: "no examples", 15, until 6 Nov) |
  | No 2xx schema | 10 |
  | Error responses not described: none, or none that says what its body holds | 10 |
  | `info.description` under 50 characters | 10 |
  | Security schemes undescribed | 5 (10 until 6 Nov) |
  | Tags undescribed | 5 |
  | No servers | 5 |

  - Examples count only where they show the call: on a request body, or on a successful response. One example on a shared error response had made 217 of OxiCloud's 235 operations look documented.
  - Each finding carries a stable key (`response_example`, `fields`, …) that claims are matched on.
  - `$ref` is resolved only within the file.
  - **Finding the spec** ✅ (16 Oct): files named `openapi*`/`swagger*` first, then any YAML or JSON in an `openapi`/`swagger` folder, then files named like `api.yaml` or `public-api.yaml`, at most 4 fetched. The parser drops files that aren't specs. Matching by name alone missed 4 specs in the comparison (dagu, jupyter_server, traceroot, ChurchCRM). The classifier's "owns a spec" evidence still uses names only, so the measured label numbers stay valid.
  - **Specs of a generated API client come last** ✅ (9 Nov): a spec inside the code openapi-generator wrote (a folder below the root that holds `.openapi-generator/`), or at the top of the package it wrote into, is measured only when the repo has no other spec; `openapitools.json`, the generator's settings, is no longer fetched as a candidate. At boxlite, DocScout had measured `apps/libs/analytics-api-client/swagger.json`, the input of a client for an analytics service outside the repo (8 operations), and before that a Go client's copy of the cloud API (`apps/libs/api-client-go/api/openapi.yaml`), not boxlite's own `openapi/box.openapi.yaml` (54 operations). On the 93 listed picks of 9 Nov the rule changes only boxlite, the one with a `.openapi-generator/` folder. ⏳ It still doesn't reach box.openapi.yaml: the worst spec among those fetched is measured, which is now the runner's internal API (swag-generated, 11 operations); whether to measure a repo's main spec instead is open. Checked 9 Nov: 28 of the 93 picks have 2 or more specs among the 4 fetched, and in 13 the worst isn't the biggest. "Biggest" isn't a safe rule either: openfoodnetwork's newer v1 has 7 operations against v0's 49, and pydio's v2 has 24 against v1's 120; several others are copies of one spec (fastcrw, daikoku).
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

**Install commands aren't endpoints** ✅ (17 Oct): `curl` lines that pipe into a shell (`| sh`, `| bash`) or fetch from a download host (raw.githubusercontent.com, github.com, get.docker.com) are skipped. mycart's only "endpoint" was its install line, which invented a "1/1 endpoints have no description" gap and made it the day's top pick (76). Prose docs remain the weakest measurement: only endpoints written in the docs are counted, so a README that documents 3 of 40 endpoints looks small; and a section is checked for the presence of a description or example, not its quality.

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

**Gaps too small to report** ✅ (17 Oct): fewer than `[report] min_effort_units` (5) operations or endpoints needing work. The repo isn't reported, Gemma doesn't review it, and it's checked again after `recheck_after_days`. Gaps of unknown size ("check manually") are kept. Why: Render's first picks included "1/1 endpoints have no description" (mycart), an 85%-complete page with 1 endpoint (ergo) and 3 of 17 endpoints (shkeeper.io). The smallest projects you'd act on in the comparison grading had 11 and 12 (local-settle-backend, ChurchCRM). The website applies the same rule when it publishes, so picks reported before the rule drop out too.

## 10. Before you contribute (M1; top 10 only, about 3 API calls each)

- **Already claimed? Per gap** ✅ (6 Nov, M6 step 6c; Gemma decided per project from 17 Oct, word matching before that).
  - **Open PRs that change the measured docs file are measured** ([analyze/pr_measure.py](../docscout/analyze/pr_measure.py)): the file in the PR against the version it started from (the merge base), with the same scorer. A PR claims what needs work before it and not after: per gap key, the operations it fixes and the fields it describes. Operations it adds or removes don't count. A PR is measured again only when its head commit changes. About 3 GitHub requests for each PR that changes the file; none for one whose file list settles that it doesn't.
  - **A PR that doesn't change the measured file claims nothing,** unless the spec is generated: then Gemma judges it, one gap at a time, from its title, description and changed files.
  - **Comments are Gemma's call, one gap at a time,** and only on help requests that ask for this work (section 21, 6b); bots' comments aren't read. An offer counts for 30 days from the person's last comment on the issue; once they open a PR for the issue (one whose title or text names or links it), the PR is measured instead. Until 8 Nov any open PR of theirs ended the offer: at docling-pipelines, two PRs for other issues had ended an offer on #296. An older offer is shown as one to ask about, not as a claim.
  - **The work left** is what needs work on the main branch, less what open PRs fix and the gaps live offers take. A pick goes below the rest only when the work left is under the size cutoff (5); otherwise it shows "Partly claimed", one line per claim ("Open PR #9 adds descriptions to 4 operations") and the work left.
  - **Why:** on 6 Nov, none of the 15 claims Gemma had made holds up. 7 of the 14 flagged PRs were closed, and the 7 open ones, measured, fix no gap; the comment "claims" were offers on issues about something else.
  - **When Gemma can't answer:** retries (5, 20, 60 s), then the other Gemma model (`fallback_model`). If both fail, the pick shows "not checked yet", never a guess, and the next run asks again. Not asked again while a project's open PRs and comments are unchanged.
- **Checked again every day** ✅ (17 Oct): once a day for `[checks] recheck_claims_days` (7) after a project is reported, so a pick can be claimed after it's shown, including by another DocScout user. A claim that has gone (the PR was closed) is cleared. M6 step 6d replaces the 7 days with checks for as long as a pick is listed (section 21).
  - The laptop report's "Still open from earlier" lines show ⚠️ with what was found.
  - About 3–5 GitHub requests per project; Gemma is asked only when its comments changed.
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
4. ✅ **Claims** (17 Oct; per gap since 6 Nov): whether someone is already working on the gap, from the issue comments and, on a generated spec, the PRs that don't change it; other PRs are measured, not judged (section 10). On the laptop this uses the local model: one question per new pick and per earlier pick whose PRs or comments changed, with an 8,192-token context (bike4mind's question was about 3,100 tokens, too close to the 4,096 used for reviews).
5. ✅ **Help requests** (6 Nov, M6 step 6b): whether each maintainer's request asks for the work DocScout found (section 21). Asked in the review, once the project itself is accepted, and once for projects reported earlier; again only when an issue's text changes. Only a request for this work earns the bonus, the looser activity check and the "Maintainers asked for help" line; claims are read only from its comments.

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
- ✅ **A second model** (17 Oct): `[llm] fallback_model` is asked when the first can't answer after its retries (busy, down, unknown, or a malformed answer), for reviews, drafts and claims; the report records the model that answered. Off by default; on Render it's `gemma-4-26b-a4b-it` (schema mode works; a review took 4.7 s).

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
  docs/ PLAN.md ✅  comparison/ METHOD.md ✅ RESULTS.md ✅ skill/SKILL.md ✅ (as tested; frozen)
  skills/find-api-docs-to-contribute/SKILL.md ✅   # the public skill, for Claude Code and other Agent Skills tools
  docscout/
    cli.py ✅  __main__.py ✅  errors.py ✅      # init set profile run status schedule draft done ignore score discover eval bench-llm
    settings/ config.py ✅ profile.py ✅ languages.py ✅ setup_wizard.py ✅ default_config.toml ✅
    find/     discover.py ✅ github.py ✅ health.py ✅ classify.py ✅ evidence.py ✅
              sources/ awesome_selfhosted ✅ repo_search ✅ help_requested ✅ code_search ✅
    analyze/  tree.py ✅ gaps.py ✅ elsewhere.py ✅ checks.py ✅ scoring.py ✅ safe_yaml.py ✅ pr_measure.py ✅ (M6)
              apitypes/ base.py ✅ rest.py ✅ openapi.py ✅ rest_prose.py ✅     # graphql.py, grpc.py, … (later)
    llm/      base.py ✅ ollama.py ✅ openai_compat.py ✅ memory.py ✅ review.py ✅ draft.py ✅ claims.py ✅ help_requests.py ✅ (M6)
    run/      pipeline.py ✅ daily.py ✅ db.py ✅ lock.py ✅ notify.py ✅ report.py ✅ sanitize.py ✅ watch.py ✅ keep_open.py ✅ (M6)
              scheduler/ __init__.py ✅ linux.py ✅ · macos.py · windows.py (M5)
    measure/  evaluate.py ✅ reclassify.py ✅ llm_eval.py ✅ bench.py ✅ claims_eval.py ✅ (M6: `docscout eval-claims`)
    hosted/   picks.py ✅ atlas.py ✅ atlas_store.py ✅ billing.py ✅ web.py ✅ search.py ✅ job.py ✅ templates/index.html ✅ (section 20)
    (M4: find/safe_fetch.py)
  tests/ ✅ 294 tests (261 and 12 skipped without the `hosted` extras and mongomock) · test_store_contract.py runs every store behavior against SQLite and Atlas · fixtures/specs, fixtures/readmes, fixtures/labeled_repos.csv ✅ · fixtures/m6/ (M6's test set) ✅
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

**Gemma for the two judgments code still makes from words** (decided 17 Oct, after the deadline):
- **Is the help request about the API docs?** Moved to M6 (section 21) on 6 Nov: of the 23 listed picks with a help request, only 5 ask for the work DocScout found.
- **Static JSON datasets** (found 6 Nov): free-llm-api-hub publishes about 30 static JSON files (no server, no parameters, no auth) and passed Gemma's review as a REST API, though most of DocScout's REST checks don't apply to it. Decide whether such projects should be listed; M6 already drops this one, since its only help request (#180, copy buttons on the API page) doesn't count.
- **Which prose lines are real endpoints?** Today patterns find them (`GET /path`, `curl` lines). Gemma would confirm which of the found lines are the project's own API endpoints, catching what the install-command rule doesn't. Prompt v3 showed Gemma copying measured facts instead of judging, so the question would be narrow (one line at a time, or a list to accept or reject), and measured before it's switched on.

Both add Gemma requests and time to every run.

Re-checking still-open items for changes (docs fixed by someone else, a PR merged); pre-contribution message drafts; learning from merged or rejected PRs; running the LLM only when plugged in or idle; new API types (GraphQL, gRPC, AsyncAPI, OpenRPC, library/SDK docs via help requests); Up For Grabs as a seed; GitLab and Codeberg; a dashboard; Spectral lint; standalone executables.

## 20. Hosted version (16 Oct)

For writers who'd rather not run anything: no terminal, and no 6 GB of free memory, which Gemma pushed this laptop to its limit for in every comparison run. It also serves the challenge's "something someone would actually pay for".

**Built on branch `hosted`:**
- **The job** (`docscout.hosted.job`, a Render cron job; every 6 hours since M6 step 6d): the first run of the day that finds the day's main run not done runs `docscout run` with [deploy/render.toml](../deploy/render.toml), whose memory is in Atlas collections (`[storage] backend = "atlas"`); the other runs run `docscout look` (section 21). Each publishes the open picks, also after a failed run. `DOCSCOUT_ATLAS_DATABASE` points the job, the commands it starts and the website at another database, for a dry run on a copy.
- **Model:** Gemma 4 31B (`gemma-4-31b-it`) through Google's OpenAI-compatible Gemini API endpoint, on the free tier. Google lists `gemma-4-31b-it` and `gemma-4-26b-a4b-it` for the key. Under load it answered 500 or 503 to about half the requests (16 Oct), so busy answers (429, 5xx) are retried after 5, 20 and 60 s, or after the provider's `Retry-After`, and then Gemma 4 26B is asked instead (17 Oct, `fallback_model`). Only schema mode returned clean JSON; JSON mode on the 26B returned its "thoughts".
- **MongoDB Atlas** (free tier):
  - **DocScout's memory, in collections** ✅ (17 Oct; until then a SQLite file in GridFS, copied in and out around each run). Render cron jobs start on an empty machine, so everything DocScout remembers lives in Atlas:
    - `repos` (one document per repo checked), `findings` (each gap, with its details as an embedded document, so they can be queried), `runs`, `run_state`, `sweep` (the search cursor) and `counters` (run and finding numbers);
    - "the latest finding of each repo" is an aggregation pipeline (`$sort`, `$group`, `$lookup`);
    - `AtlasStore` ([hosted/atlas_store.py](../docscout/hosted/atlas_store.py)) has the same methods as the SQLite `Store`, and contract tests run every behavior against both (mongomock stands in for Atlas). The command-line tool keeps its local SQLite file;
    - why: the switch makes Atlas the store DocScout works in, not a place to park a file (for the "Best Use of MongoDB Atlas" category);
    - the first run with empty collections moves the GridFS file in (the file stays as a backup). Checked on the real Atlas in a temporary database: 695 repos, 43 findings and 4 runs in 5.5 s, and every query gave the same answers as SQLite, including the website's 25 picks;
  - the picks: one document, rewritten after each run;
  - subscriptions: no names or email addresses kept.
- **Website** (`docscout.hosted.web`, Starlette and Jinja2, a Render web service). Redesigned on 16 Oct after "a wall of text": a short welcome, 3 how-it-works steps, cards with labels (language, stars, effort, docs published, help requested, not claimed, outside PRs merged), "What needs doing" and Gemma's note up front, the details folded away (`<details>`, no JavaScript):
  - every open pick, checked every 6 hours, best score first (since M6 was deployed on 6 Nov, section 21). Until then, the picks from the last 7 days: each stayed for 7 daily runs and wasn't checked again, which is how the list fell to 9 once the pool ran dry;
  - the top 3 free (5 until 17 Oct; since M6, the best 3 found in the last 7 days, topped up with older picks), the rest after a Stripe Checkout subscription;
  - subscribers can switch to newest first (17 Oct): the day it was found, then best score. Every card says when it was found, and a "New" label marks the last 24 hours;
  - subscribers can filter the list (8 Nov): by the size of the job (small, medium or big, the card's effort label) and to picks whose maintainers asked for help. They sit behind a filter icon that opens a small panel (a `<details>` element, so no JavaScript), and the active ones show under the heading as chips that remove them, with the match count; the first version, a row of controls, looked cluttered. Sorting and pages keep the filters. Visitors get no filters, since a filter would show them picks beyond the free 3. On the 93 open picks of 8 Nov: 14 small jobs, and 2 big jobs with a help request;
  - anyone can search by what a project is about (8 Nov; [hosted/search.py](../docscout/hosted/search.py)): a plain form under the heading, so still no JavaScript. Subscribers get the matching picks, with sorting, filters and pages kept; visitors get how many match and the free picks among them ("25 of 92 match, 1 of them free"), a nudge to subscribe that gives nothing away. A search that finds nothing suggests the kinds of project with the most picks. The rules:
    - it looks through each pick's name, description, GitHub topics (published with each pick since 8 Nov, so they're searchable after the first run with this code) and language; not Gemma's note, which is about the docs;
    - every word must match; plurals match simply; a word of 5 letters or more also matches longer words that start with it ("photo" finds "photography"; "java" doesn't find "javascript"); words every pick shares ("api", "rest") are ignored;
    - a word naming a kind of project expands to the words its projects use: "ai" also finds `llm`, `rag` and `machine-learning`; 19 kinds, from AI and blockchain to healthcare. Words a project uses rather than is about stay out of the lists, tried on the 92 picks of 8 Nov: "docker", database engines, "dashboard", "raspberry pi", bare "streaming" (an AI gateway's streamed answers matched "media") and "orchestration" (AI agents matched "devops"). On those picks: AI 25, media 13, storage 10, DevOps 9, monitoring 9, blockchain 1;
    - in memory, not Atlas Search (decided 8 Nov): about 90 short records live in one document, so Atlas Search would mean storing each pick as its own document, moving paging, sorting and the paywall into the query, and tests that mongomock can't run, for typo tolerance and relevance ranking the list doesn't need yet. Worth revisiting once the list is in the thousands; only `search()` would change;
  - the paywall is enforced on the server, so the page holds only what the visitor may see;
  - subscribers page through the list, 10 picks a page (server-side pages: infinite scrolling would need JavaScript);
  - picks someone may already be on go below the rest (17 Oct), because every pick is checked for claims again each day (section 10). Since M6, only when the unclaimed work is under 5 operations or endpoints; otherwise the card says "Partly claimed" with the work left;
  - each card's "What needs doing" names the biggest gap (17 Oct; it was the first one, so statewave showed "2/19 endpoints have no description" instead of "19/19 endpoints have no response example");
  - the page states Gemma's role plainly: it reviews every candidate and turns away the ones that aren't real apps with an API, which raised precision from 76% to 85%.
  - no JavaScript, and a Content-Security-Policy that allows no scripts;
  - text escaped, and links only to GitHub URLs DocScout trusts. They open in a new tab (5 Nov), so the list stays where the reader left it.
- **Subscriber pass:** an HMAC-signed, HttpOnly cookie for 31 days, issued only after Stripe confirms the session is complete and paid.

**Decisions:**
- **Render, not DigitalOcean.** The $50 Hacktoberfest credit covers it. DigitalOcean's cheapest fit was about $48 a month, and signing up asked for more than the plan. On Render:
  - the cron job is the agent's runtime ("your project's AI runtime");
  - the website is "an agent's front end".
- **Google AI Studio for Gemma.** It's free with no card, and it's Google serving Gemma. DigitalOcean's Inference also serves Gemma 4 ($0.18 / $0.50 per million input / output tokens), but the account wanted a charge. OpenRouter (`google/gemma-4-31b-it:free`) is the fallback: one setting.
- **Price: $2 a month, not weekly** (17 Oct; it was $3). Card fees (about $0.30 plus 2.9% per charge) leave about $1.64 of $2, and weekly billing would pay the fixed fee four times.
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

**The candidate pool ran dry by 24 Oct** (found 5 Nov). The runs of 17–23 Oct checked the full 200 repos and published 5–15 picks each, and the 7-day list grew to about 70. By 24 Oct DocScout had checked about 3,000 repos: every awesome-selfhosted app in the star range (1,115) and every page of the 24 repo-search slices, each gone through 2–4 times. A checked repo isn't checked again for 90 days (`recheck_after_days`), so since 25 Oct a run finds only the repos new to its sources: 9–152 (about 50 on average) instead of 200, and 0–3 new picks. The older picks left the 7-day list, which fell to 9 on 5 Nov. Nothing was deleted: the picks are still in Atlas. Decided 6 Nov: open picks stay listed and are kept true (M6, section 21); more sources come after it.

**Code search added** (10 Nov, after only 3 picks were added on 9 Nov; section 8, source 4). Of the 3,520 repos checked by then, awesome-selfhosted gave 1,116 (44 of the 93 listed picks), repo search 1,910 (39) and help requests 494 (10). Checked live and read-only on 10 Nov: the first pages of the 16 queries gave 1,436 repos new to DocScout, and 191 passed the cheap checks, which now cost nothing. Of a random 40 of those 191, run through the full checks without Gemma: 18 have fewer than 2 committers in 90 days, 2 no merged outside PR, 4 no reportable gap, and 16 a spec with gaps, 11 of them scoring at least 25 (`min_score`). So a main run, with about 150 of its 200 repos from code search, should reach Gemma's 30-review cap; how many Gemma accepts is open, since code search also finds libraries, SDKs and clients (flask-security, an iOS app). Each full check took 5–8 s, so the main run grows by about 20 minutes. Deeper in the results fewer pass the cheap checks: 4–5% of new repos with an `openapi.yaml` under 1 KB, 8% at 2 KB and at 20 KB (200 each, 10 Nov), so the queue starts with the largest files, and a run reads about 25–35 pages, up to 4 minutes of waiting for code search's 10 requests a minute. With the splitting, all of the about 380,000 results can be reached, enough for months at about 150 full checks a run. Big projects (405 turned away for their size) stay off for now.

**⏳ Still to do:**
- ✅ Gemma 4 31B on the 58 labels: 85% precision, 90% recall (section 2);
- ✅ deployed: the public GitHub repo, the Render Blueprint, Atlas access for Render;
- a real end-to-end test payment on the live site, in test mode;
- before real payments (after the deadline): subscribers are recognized only by a signed cookie in their browser, so they lose access on another device or after clearing cookies; renewal doesn't extend the 31-day pass, and cancelling doesn't end it early. A "restore access" step through Stripe's customer portal, and passes that follow the Stripe subscription's status, fix all three;
- after the deadline: check published projects again, so one that still has the gap and isn't claimed stays or comes back: now M6 (section 21).

## 21. M6: open picks stay listed, and stay true (planned 6 Nov)

The website's list fell from about 70 picks to 9 (section 20), because a pick leaves after 7 days and a listed project is never checked again. Listing every open pick fixes the count, but only if every card stays true. Checking all 120 listed picks on 5–6 Nov found four ways a card goes wrong.

### What the checks found

| The card says | What was true (5–6 Nov) | How it was checked |
|---|---|---|
| ⚠ Someone may be on it (15 picks) | **None holds up.** 7 of the 14 flagged PRs are closed, but their claims are still shown, because claims are checked only in a pick's first 7 days. The 7 still open fix none of the measured gaps: they're features and fixes that edit the spec for their own changes. wildduck's adds 11 operations, none documented; devtrack's removes 2. The comment "claims" are offers on issues about something else (docling: a code fix), on issues since deleted (stellar_Earn) or closed (agora), on a deleted repo (Stellar-MarketPay), or not offers at all (holographic-memory) | Each PR's spec measured before and after, with DocScout's own scorer; comments read |
| Maintainers asked for help (23 picks) | **Only 5 ask for the work DocScout found** (OpsiMate, zowe, agora, Drix10, QualityOnDemand). 8 ask for other API-docs work (three outdated statements, Tauri commands instead of the REST spec, a Node.js library reference), and 10 aren't about API docs (a licence badge, code bugs, a new provider, Go doc comments, copy buttons on a docs page). Labeled 6 Nov, the 6 borderline ones by you ([tests/fixtures/m6/help_requests.json](../tests/fixtures/m6/help_requests.json)). 8 of the 25 issues are now closed or deleted | Every issue read in full |
| The gap's numbers | The measured docs file changed for **51 of 106** picks within 2–3 weeks, and 2 files are gone. Measured again, the work needed grew for 30 of 48 specs (new endpoints without docs), stayed the same for 13 and shrank for 4. None of the 4 gained a request or success example: devtrack and openreader removed operations, and OxiCloud (232 → 78 operations needing work) and open-wearables (136 → 91) added one example to a shared error response that every operation refers to (next row) | The file's version when found and now; changed specs measured again |
| "N operations have no request or response examples" | **Too lenient.** The check counts an example anywhere in an operation. Of the 12,315 operations in 87 spec picks, 582 have examples only on error responses, usually one shared error message (OxiCloud 217, open-wearables 118, Inventoros 79), and 300 only on a parameter, like `limit=10`. Neither shows what a call takes or what it returns. Counted the way a reader needs (below), 10,988 of the 11,717 operations that return something have no success example, and 3,733 of the 4,179 that take a request body have no request example | Where each example sits, in every spec pick |
| The project | 1 repo deleted, 1 renamed, 4 with no push for 30+ days (2 of them past 50) | One batched GraphQL check |

What this means:
- **Keeping picks is sound.** Gaps don't close within weeks: none of the 48 changed specs gained a request or success example, and projects add endpoints faster than they document them.
- **Measuring has to count the right examples**, or a shared error example looks like hundreds of documented operations, in the gap check and in PR measuring alike (3).
- **The card must be checked again:** claims and help requests change daily, and the numbers drift.
- **Gemma can't be asked on every change.** 60 of the 119 live picks had an open PR updated in the last day: about 60 questions a day now and 500 at 1,000 picks, beyond its free tier. Measuring a PR needs no question.

### Goal and exit check

Every listed pick is still open, and every line on its card was checked recently: claims, help requests and whether the project exists, within 6 hours; the gap's numbers, within 6 hours of the docs changing; the health checks, within 7 days.

- **Claims:** at most 1 wrong of the 15 claimed picks of 6 Nov (today none holds up), and every real claim in the test set found.
- **Help requests:** at least 21 of the 23 agree with your labels, and none of the 10 that aren't about API docs counts.
- **No listed pick** whose repo is deleted, archived or without a push in 60 days, and no card that shows a closed issue as a help request.
- **A new PR or offer** on a listed pick shows on its card within 6 hours.
- **Every open pick is listed** once the backlog is cleared.
- **The daily run takes at most 10 minutes longer** at today's 120 picks, and each of the other runs at most 5 minutes.

### How it works

**1. A pick stays listed while it's open.**
- No age limit on the website (`[picks] keep_open`). The laptop keeps its daily reports and "Still open from earlier" lines.
- A pick leaves the list when:
  - the work left falls below the size cutoff (5): it goes back into the normal pool, to be checked again after 90 days like any repo, with the reason "docs fixed";
  - the project fails the health checks: back into the pool, reason "went quiet";
  - the repo is deleted or made private: "ignored", reason "repo gone".
- A renamed repo keeps its pick under the new name. If the new name is already in the memory, the two records merge, so the project isn't listed twice.
- Each card shows when it was found and when it was last checked: "Found 20 Oct · checked 2 hours ago".

**2. A look at what changed, every 6 hours: one request per 60 picks.**
- One GraphQL request asks, for each pick: its current name, whether it's archived, its last push, the version of the measured docs file, its open PRs (how many, and the latest update), and each help-request issue's state, update time and comment count.
  - Checked 6 Nov: 120 picks in 2 requests and 19 seconds, 1 point each of the 5,000 an hour. Renames are followed, and a deleted repo or issue fails only its own part of the answer.
- The answers are kept with the pick (`details.watch`) and compared with the last look:
  - docs file changed: measure it again in this run;
  - PRs or comments changed: check claims in this run;
  - a help-request issue closed or deleted: off the card, and the score's bonus recomputed;
  - repo renamed, archived or gone: as in 1;
  - nothing changed: no further requests.
- Prose docs span several files, which the look can't see, so the weekly re-check covers them (3).

**3. The re-check** ✅ (built 6 Nov as one check, [run/keep_open.py](../docscout/run/keep_open.py)).
- A re-check runs the checks a new candidate gets: health from GitHub now (licence, stars, committers, outside merges), then the docs measured again by the same code that found the gap. It runs in the run that spots a docs change (within about 6 hours of it), the first time a pick is looked at under M6, and at least every 7 days. If more are due than the run's cap allows, the rest wait for the next run. The look itself covers pushes and archiving.
- A pick whose docs got fixed (no gap, or less than the size cutoff left), that fails the health checks, or whose docs may be elsewhere with no help request that counts, leaves the list.
- The pick keeps its found date, its Gemma review and its place in the list. The new numbers replace the old ones, and a short history is kept (`details.history`: date, operations needing work, score).
- When the numbers move by a fifth or more, Gemma rewrites why the docs matter and the first steps, which quote the numbers.
- The measuring itself changes (confirmed 6 Nov, "Measuring changes" at the end of this section): examples are counted the way a reader needs them, so a shared error example can't look like hundreds of documented operations, and two gaps DocScout missed are counted, fields without descriptions and error bodies.

**4. Claims are per gap, and PRs are measured.**
- Each gap gets a stable key, stored with its finding: `description`, `parameters`, `fields`, `request_example`, `response_example`, `success_schema`, `errors` and so on for specs; `request_example`, `response_example`, `status_codes` and so on for prose.
- **An open PR that changes the measured docs file:** DocScout measures the file in the PR against the version the PR started from (the merge base, so later changes on the main branch aren't credited to the PR). The PR claims the operations that need work before it and not after it.
  - Operations it adds or removes don't count, and neither does progress inside an operation that still needs work: osk-backend #356 describes one parameter of an operation whose others are still undescribed.
  - Checked 6 Nov on all 14 flagged PRs, including PRs from forks.
- **A PR that doesn't change the measured file** can't claim its gaps, when the spec is hand-written.
- **Generated specs** (11 of the 91 spec picks): the real work happens in code annotations, so Gemma judges the PR, one gap at a time.
- **Offers in comments:** Gemma judges them, one gap at a time, and only on help requests that ask for this work (5). An offer counts for 30 days from the person's last comment on the issue (today: 3 months), so a new comment from them restarts the 30 days. Once their PR for the issue appears, the PR is measured instead. After 30 days of silence the offer stops counting, but the card still mentions it, so a writer can ask whether they're still on it.
- A PR is measured again only when its head commit changes.
- **The work left** is the work on the main branch, minus what open PRs fix, minus the gaps that live offers cover. A pick goes below the rest only when the work left is under the size cutoff. Otherwise it keeps its place, with one line per claim: "PR #2667 removes 2 operations; the other 133 still need work."

**5. Help requests must ask for this work.**
- **Bounty programs are filtered by code first:** labels and bots such as Stellar Wave and `drips-wave[bot]` go into a setting, like today's bounty labels. Their issues aren't help requests, and their applicants aren't claims.
- **Gemma reads each issue** (title, labels, the start of the text) next to the gaps, and answers one of three ways, with a quote that code checks is in the issue:
  - **asks for this work:** the score bonus, "Maintainers asked for help" and the looser health check; it can make a "docs elsewhere" pick listable, and its comments are read for claims;
  - **other API-docs work:** shown as a related issue, with none of the above;
  - **not API docs:** not shown.
- A "docs elsewhere" pick has no measured gap, so there "this work" means work on the project's API reference.
- Features of a docs site (copy buttons, search, styling) aren't API-docs work, even on the API page (free-llm-api-hub #180).
- The looser health check still runs before Gemma. If Gemma then says the issue doesn't ask for this work, the repo must pass the normal thresholds, from numbers already fetched.
- Each issue is asked about once, and again only when its text changes.
- **Each request's text is read before Gemma is asked** ✅ (fixed 8 Nov). On the website, the look runs asked about listed picks' requests without fetching their text, so all 41 requests on the site were judged from title and labels alone; the test set, which has the text, didn't show it. writerslogic/warm #10, "Node.js API reference with usage examples", counted as a request for the REST spec's missing examples; its text asks for the Node.js library's ~40 methods, which is other API-docs work. Now a request without its text is fetched first (one GitHub request each), and the new text makes it due, so every listed pick's requests are asked again within the runs' Gemma caps.
- **Bug reports are filtered by code too** ✅ (8 Nov): a title in the conventional bug form ("bug(api): …", "fix: …", "[Bug] …", but not "fix(docs): …") marks a code fix, whatever Gemma answers. Gemma read docling-pipelines #296 ("bug(api): document-libraries routes deviate from their OpenSpec") as docs work in every live run, though it asks for the code to match the spec; two people had split the fix, while the card showed it as a help request nobody had claimed. A reworded question got #296 right on the test set but not with the live pick's context (3 of 3 asks still "this work"), and agreement on the test set fell to 20 and then 16 of 23 (partly the busy 31B handing questions to the 26B), so the question stayed as it was. On the test set the rule matches 2 issues, both labeled code bugs; on the 93 listed picks of 8 Nov only #296, so docling-pipelines leaves the list on the next run. The "bug" label isn't used: 2 of the 5 requests for this work carry it.

**6. The website.**
- **Free:** the best 3 found in the last 7 days, topped up with older picks when the week has fewer. **Subscribers:** every open pick, best first or newest first.
- Every card says "Comment on the issue, or open one, before you start". That's how the next writer, and DocScout, see someone is on it.
- "Picks from the last 7 days" becomes "every open pick, checked every 6 hours", on the page and in the paywall text.

**7. Runs: when, what, and their limits.**
- **The cron job runs every 6 hours** (04:15, 10:15, 16:15 and 22:15 UTC) instead of once a day. It's one schedule in render.yaml, so there's no second cron job and no second $1 monthly minimum.
- **The daily run** is the first run of the day (UTC) that finds the day's work not done, normally the 04:15 one. If it fails, the next run tries again, instead of waiting a day as now. It:
  1. looks at every listed pick;
  2. acts on what changed, within caps: up to 40 gap checks, 40 claim checks, and 30 Gemma questions for claims, help requests and rewrites (`[llm] checks_per_run`);
  3. runs the 7-day health checks that are due;
  4. finds new repos with the GitHub budget left, then Gemma reviews them, as today.
- **The other three runs** only look, act on what changed with smaller caps (20 gap checks, 20 claim checks, 10 Gemma questions), and publish the picks again. Most claims need no Gemma question, since PRs are measured.
- **A run still going** when the next one starts: the new run sees it in the memory and stops at once.
- **Within a cap**, the picks free visitors see go first, then the newest. The rest wait for the next run, and each card says when it was last checked.

Projected from the 6 Nov checks, per day:

| Listed picks | Looks | Claim checks | Gap and health checks | Gemma questions | Added time |
|---|---|---|---|---|---|
| 120 (today) | 4 × 2 requests | about 60 picks, in about 6 requests | about 3 gap checks and 17 health checks | about 5 | 5–10 min in the daily run, about 2 min in each of the others |
| 1,000 | 4 × 17 requests | about 500 picks, in about 50 requests | about 25 and 140 | up to 60 (the caps) | 45–60 min in the daily run, most of it Gemma's 30 questions; 5–15 min in each of the others |

**8. Laptop and website.**

| Setting | Laptop | Website |
|---|---|---|
| `[picks] keep_open` | off | on |
| `[checks] measure_prs` | on | on |
| `[checks] help_requests_by_gemma` | on (about 50 s a question on `e2b`) | on |
| `[llm] checks_per_run` | 5 | 30 in the daily run, 10 in the others |
| `[picks] look_every_hours` | off (the laptop doesn't keep picks) | 6 |

Each is a switch, so a problem on Render is fixed in deploy/render.toml without undoing code.

**9. Stored data.** Everything new lives in a finding's details (`watch`, `history`, per-gap `claims`, Gemma's `help` answers) or its gaps (the keys), so the SQLite file needs no migration. A rename moves the repo record to the new name in both stores, and the contract tests run each new behavior against both.

### Build order

Each step can ship on its own.

| Step | What | Exit check |
|---|---|---|
| **6a. Test set** | The 23 help requests and 15 claimed picks labeled from their full text (first pass done 6 Nov; you label the 6 borderline ones). **Real claims too:** all 15 claims of 6 Nov are wrong, so a check that never flags anything would pass a test set made only of them. Real ones are rare, since none of the 48 changed specs gained a request or success example. So the set uses open-wearables PR #1976 (merged 4 Nov: error responses documented for 32 operations, plus one shared error example that must not count as 119 examples), real offers placed next to a gap they match, and made-up cases. Small specs, before and after, kept as test fixtures. ✅ Built 6 Nov: [help_requests.json](../tests/fixtures/m6/help_requests.json) (25 issues) and [claims.json](../tests/fixtures/m6/claims.json) (the 15 flagged picks, 21 comments with names replaced, 3 PRs on a generated spec; 8 real claims to find) | Labels agreed: help requests ✅; claims ⏳ your review |
| **6b. Help requests** | ✅ Built 6 Nov: the bounty filter, Gemma's question ([llm/help_requests.py](../docscout/llm/help_requests.py)) and its effects (bonus, activity check, listing, claims, drafts, cards), the health-check order, and `docscout eval-claims`. Existing picks' requests are asked about once, up to `[llm] checks_per_run` a run. **When deployed**, of the 23 listed picks with a help request: 3 keep it (OpsiMate, zowe, Drix10), 11 stay listed without the bonus and the line, and 9 leave the list, since their docs may be elsewhere and their only request doesn't count (sciencediscovery and solongate are on the site now) | ✅ Passed 6 Nov with Gemma 4 31B: 21 of 23 picks agree; the 2 misses (bernstein, atom) are C answered B, which don't count either way; none of the 10 C picks counted; every quote found; 53 s a question on the free tier. The first try reached 18 of 23: Gemma counted requests about another API (Tauri commands, a Node.js library) because the question didn't say which spec the gaps were in, so it now names the measured spec and its file. The categories in the prompt were written with these labels in view, so the result is optimistic: new help requests are checked as they come (6e). In the 6d dry run, Gemma answered docling #296 (labeled C, a code bug) as this work, so a pick that should leave stays. Fixed 8 Nov by a code rule for bug-report titles (section 21, 5), after a reworded question didn't hold |
| **6c. Claims per gap** | ✅ Built 6 Nov: the measuring changes (section 9), gap keys, measuring PRs ([analyze/pr_measure.py](../docscout/analyze/pr_measure.py)), per-gap questions for comments and for PRs on a generated spec, the 30-day offer rule, and "Partly claimed" with the work left on cards (section 10). On six large specs the new rules match the 6 Nov script (OxiCloud: 204 of 204 operations without a success example) and take up to 8 s for a 1.9 MB spec, mostly parsing. **When deployed,** new picks are measured with the new rules; listed picks keep their numbers until 6d measures them again, but their claims are checked the new way on the next run | ✅ Passed 6 Nov: the 14 flagged PRs, measured under the new rules on GitHub as it is now, fix no measured gap (7 change the measured file, 7 don't). Gemma 4 31B found all 8 real claims in the test set, each with exactly the right gaps, and made 1 wrong one: an offer to fix code on docling #296, an issue that 6b keeps it from reading in a run |
| **6d. Open picks stay listed** | ✅ Built 6–7 Nov: the look every 6 hours ([run/watch.py](../docscout/run/watch.py)), re-checks, leaving the list, renames, caps ([run/keep_open.py](../docscout/run/keep_open.py)), the free 3, card dates and wording, `docscout look`, the job's main and look runs, and `DOCSCOUT_ATLAS_DATABASE` for a dry run. The first passes found three problems, all fixed: GitHub timed out on one 60-repo look (a failed batch is now split, and a pick it can't answer for waits); parsing large specs with the pure-Python YAML parser took most of a 76-minute run (libyaml and the JSON parser now, 4.5 times faster on an 838 KB spec); and PRs inactive for 90 days counted as claims (they don't now, as Gemma's old prompt had it). "Partly claimed" now shows only when a claim takes an operation off the work left | Dry run 6–7 Nov on a copy of Atlas, without new searches: 10 runs. The backlog of 120 picks was through its first checks by the 7th; 96 stay listed (8 on the site before), 24 leave, each with a reason (in the 7 Nov summary). Settled look runs take 1–3½ minutes; the main run's addition is estimated at 6–8 minutes (a look, plus about 14 weekly re-checks a day). The first runs after deploying take longer while the backlog clears: about 30 minutes for the first main run, then 2–13 minutes per look. ✅ You agreed with the reasons for all 24 (7 Nov) |
| **6e. Docs and launch** | The README, the public skill (claims per gap, help requests, bounty programs) and this plan; deploy, then watch 3 days of runs. You label the next new help requests as they arrive, a check of 6b's question on cases it wasn't written with. ✅ Deployed 6 Nov: the first M6 run (a main run, 23:59 UTC) took 18 minutes and the 7 Nov main run 20, both without errors; after them, 66 open picks were listed and the rest waited for their first re-check. ✅ 7 Nov: the README (a section on the website, the measuring and claim rules, `eval-claims`, the website's settings) and the public skill (help requests sorted three ways, bounty programs, the example and field rules, measured PRs, the 30-day offer rule, the work left); the dry run's database deleted from Atlas | ⏳ 3 days of clean runs (7–10 Nov), Gemma within its caps; ⏳ at least 9 of the next 10 new help requests answered as you label them |

- **Why this order:** each step goes live when it's done. 6c reads comments only on help requests that pass 6b. 6d brings the list back, and comes after 6b and 6c, so the picks that return carry correct claims and help requests (confirmed 6 Nov).
- **Tests:** unit tests for each part (recorded GraphQL answers, the PR fixtures, the merge rule, caps and priorities, the cards) and contract tests for both stores. `docscout eval-claims` measures Gemma's two new questions on the test set: live, never in the test suite, like `eval --llm`.

### Risks

| Risk | What limits it |
|---|---|
| Gemma's new questions are no better (prompt v3) | The test set first; narrow questions; quotes checked by code; each a switch |
| A PR restructures the spec (split files, moved `$ref`s), so measuring misreads it | Only operations in both versions count; if the PR's spec doesn't parse, Gemma judges it |
| A spec over 2 MB | The same cap as today; such a PR is judged by Gemma |
| Gemma busy or down | Caps, the 26B fallback, and "not checked yet", never a guess (as today) |
| A run cut off midway | Each check saves as it goes; the look's answers are saved only after they've been acted on |
| Two runs at once | A run still going makes the next one stop at once |
| More writers see the same pick | "Comment before you start"; claims checked every 6 hours |
| The list grows long | The look for changes and caps; pages of 10; filters for the size of the job and help requests, and a search by what the project is about or its language (8 Nov) |

### Decisions (confirmed 6 Nov)

1. The free 3: the best from the last 7 days, topped up with older picks when the week has fewer.
2. Offers without a PR count for 30 days from the person's last comment on the issue.
3. A pick goes below the rest only when its unclaimed work is under 5 operations or endpoints.
4. Gap checks in the run that spots the change; health checks every 7 days.
5. The laptop gets 6b and 6c, not 6d.
6. The order: 6a to 6e, so the list comes back with correct claims.
7. Looks for changes every 6 hours, not once a day.
8. Examples in two lines, counted the way a reader needs them (below).
9. Field descriptions counted, and error bodies counted in the error line (below).

### Measuring changes (confirmed 6 Nov, built in 6c)

Measured on 6 Nov on 87 spec picks, 12,315 operations.

**Examples, in two lines,** as the prose check already does:
- **Request example**, for operations that take a request body: "3,733 of 4,179 operations that take a request body have no request example".
- **Response example**, for operations that return something, which is all but empty answers like 204 No Content: "10,988 of 11,717 operations have no example of a successful response".
- So a GET that returns a list needs only a response example; a POST that sends JSON needs both; a DELETE that answers 204 needs neither. For a GET, the request is the address and its parameters, which the parameter line covers.
- Examples on parameters (`limit=10`) or on error responses count for neither line.
- Most picks' example gaps grow: wppconnect-server, the top free pick on 6 Nov, goes from 9 of 158 operations without examples to 156 of 158 without a success example; OxiCloud from 18 of 235 to 204 of 204.

**Fields without descriptions,** a new line: "2,140 of 3,400 fields have no description (e.g. `User.status`, `Order.total`)".
- It counts every field a reader sends or gets back: in request bodies and in success and error responses, including nested objects and array items, and each field once, even when many operations share it. Fields of schemas no operation uses don't count.
- Parameters keep their own line ("operations with parameters without descriptions"), so between the two lines, everything a reader sends or receives is covered.
- On 6 Nov, 21,338 of the 43,838 top-level fields in the picks' shared schemas had no description (48%). At least half were undescribed in 52 of 77 picks, and all of them in 9. The full count, nested and inline fields included, is measured in 6c.
- An operation whose request or response fields lack descriptions needs work, so it counts toward the gap's size.

**Error bodies:** an operation documents its errors only when at least one of its error responses describes its body. 2,855 of the 8,495 operations that list error responses don't.

**Not added:** request bodies without a schema, which only 10 of 4,168 are.

**Weights,** still out of 100: description 20 · parameters 10 (was 15) · fields 10 (new) · request example 7 and response example 8 (were "examples", 15) · success schema 10 · errors 10 · overview 10 · security schemes 5 (was 10; usually one or two sentences of work) · tags 5 · servers 5.

The public skill gets the same rules (6e). The comparison rounds keep the numbers measured at the time.

**Not in M6:** more sources, the other answer to the dry pool (code search added 10 Nov, section 20); a way for subscribers to restore access (section 20). The language filter once listed here is covered by the search (8 Nov): "go" or "python" finds the picks in that language.
