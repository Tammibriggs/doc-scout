# DocScout plan

DocScout finds open-source projects that **(a)** serve an API, **(b)** have documentation gaps you can fix, and **(c)** are likely to accept your pull request. Once installed, it runs every day without being started by hand and gives you a short ranked list. Each item lists the exact gaps, links to start from, and warnings about anything that could get the PR rejected. It starts with REST APIs, and other API types plug in as modules.

**Deadline: Monday 19 October 2026**, one week from 12 October.

## 1. Status and timeline

**Build stages (milestones).** Each stage is usable on its own. With one week, M3 (daily runs) comes **before** M2 (LLM), so the unattended test runs for 3 days instead of 1. Each stage lists what must ship by the deadline and what ships only if there's time.

| Stage | Must ship | If time allows | Dates |
|---|---|---|---|
| **M0. Prove discovery** | ✅ Code (commits `3d3e49e`…); ⏳ **your accuracy check** (section 2) | — | Mon 12 – Tue 13 Oct (morning) |
| **M1. Useful manual report** | OpenAPI spec gap scorer; endpoint completeness in prose docs; "docs elsewhere / generated, check manually" flag; generated-spec warning; scoring with your languages ranked higher; SQLite (seen, ignored, done); safe Markdown report; `run --no-llm`, `ignore`, `done`, `score` | Claim check (open PRs, "I'll take this"); CLA, DCO and AI-policy badges; local-setup badge | Tue 13 – Thu 15 Oct |
| **M3. Daily runs on Linux** | `run --if-due`, file lock, offline check and resume, a cursor through the search slices, `notify-send`, a 401 alert, `schedule install/uninstall/status` for systemd | Quiet-day rules; "pool running dry" warning | Fri 16 Oct |
| **M2. LLM layer** | First steps for the top candidates; second opinion for unclear types (0.4–0.7) with the 0.8 cap; when the LLM is unavailable, "LLM review skipped" plus the fix | Measuring the LLM against your labels | Sat 17 Oct |
| Unattended test | Runs Fri 16 → Mon 19 in the background: no manual starts, survives a reboot and going offline | | Fri 16 – Mon 19 Oct |
| Polish | README, demo report, a real contribution made with it | | Sun 18 Oct |
| **Deadline** | | | **Mon 19 Oct** |
| **M4. Read external docs** | | **After the deadline** | |
| **M5. macOS and Windows support** | launchd and Task Scheduler setup, notifications and file lock on both, CI on 3 operating systems, `pipx` packaging, a fresh-install test on real machines | **After the deadline** | |

**If the schedule slips:** the "if time allows" items go first, then M2 shrinks to first steps only. M1's must-ship items stay, because without them the tool can't tell you what to fix.

**macOS and Windows are planned, not dropped.** Everything built so far is already plain cross-platform Python:
- user folders come from `platformdirs`;
- the secrets file is created private on Unix, and the permission call is skipped on Windows;
- the windowless `docscout-bg` entry point exists.

M3 builds scheduling behind a small per-OS interface (`scheduler/linux.py`), so M5 only adds `macos.py` and `windows.py`. Their exact settings are already worked out (section 10).

**How work is saved:** `main` holds finished work. Each stage gets its own branch (`m1-report`, `m2-llm`, …), merged into `main` when its exit check passes. There's a commit at each key stage, always with tests passing, and never with secrets or local samples.

## 2. The next step: the M0 accuracy check

This is the gate for everything after it. It answers two questions: does DocScout find real API projects (≥ 70% accuracy), and can your laptop run the local LLM?
1. Create a GitHub token, then run `docscout init`.
2. Run `docscout discover --sample 60 --csv sample.csv`.
3. Label the `label` column.
4. Run `docscout eval sample.csv`.
5. Run `docscout bench-llm` with other apps closed.

Detailed instructions are in the README's "Stage M0" section. **Result:** the accuracy per source and the LLM speed and memory figures. I then tune the classifier, switch off any source below 50%, and save the labeled CSV as a regression test.

## 3. Success criteria

| Metric | Target | Checked in |
|---|---|---|
| Reported items that really serve an API **and** have a real docs gap | ≥ 70% | M0 (classifier), M1 (gaps) |
| Items per weekly report you'd actually act on | ≥ 5 | M1 |
| Daily run time without the LLM, on your laptop | ≤ 10 min | M1 |
| Manual starts needed | 0, including after reboots, sleep and offline days | M3 (Linux), M5 (macOS and Windows; also on battery) |
| Silent failures | 0. An expired token or repeated failures always cause a notification | M3 |
| Setup | At most 3 questions; usually 1–2 | ✅ M0 |
| Fresh install on macOS or Windows | `pipx install`, `init` and `schedule install` work first time | M5 |

## 4. Decisions made

- **Platform and output:**
  - GitHub only; Hacktoberfest isn't part of the scoring.
  - Output is a Markdown report plus a desktop notification, with a new dated file per run. Days with nothing new stay quiet.
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
- **Process:** commits at key stages; a branch per stage.

## 5. What real data showed (checked live, 11–12 October)

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
| Which LLM: local, hosted or none | Unless `--llm` is given. Choosing hosted adds a model name and an API key |
| GitHub token | Only if none is set. It's tested with GitHub and not saved if rejected |

**Changing settings without questions:**
- `docscout set` changes any other setting: `--languages`, `--only-these-languages`, `--sizes`, `--llm`, `--model`, `--base-url`.
- `discover` (and later `run`) takes the same flags for a single run.
- Any setting given as a flag skips its question in `init`.

**Where settings live:**
- `docscout profile` shows the settings in plain sentences.
- Settings are saved to `[profile]` and `[llm]` in the user's `config.toml`; secrets go to `secrets.env`, readable only by the user.
- All other tuning lives in [default_config.toml](../docscout/default_config.toml) as "advanced".

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
  - **Generated specs** (a `DO NOT EDIT` header, or CI that regenerates the file) keep their score, but the suggestion becomes "edit the code annotations".
- **C. Docs only in prose.** Each endpoint in the README or docs is checked for: a description (25), a request example (20), a response example (25), status or error codes (15) and auth (15). If the docs are at least 80% complete, the gap is set to 35 and the suggestion becomes "turn them into an OpenAPI spec".
- **D. No docs found.** Gap = 75, only when type confidence is at least 0.8 and no docs were found elsewhere. Always marked *unverified*.
- **Docs elsewhere or generated at runtime.** Detected from the homepage, a docs link in the README, a sibling `*docs*` repo, or a Swagger UI, ReDoc or `/docs` mention. The gap is capped at 50 and the item is marked "check manually" until M4.

```
score = gap × (0.5 + 0.5·health) × type_confidence + issue_bonus (help wanted +10, good first issue +5, docs label +5; max +15)
        + language bonus when the repo is in one of your preferred languages (M1)
```

**Effort** is counted in operations or endpoints needing work: up to 10 is S, up to 40 is M, more is L.

## 10. Before you contribute (M1; top 10 only, about 3 API calls each)

- **Already claimed?** Checks open PRs that touch docs or the spec, and phrases like "I'll take this" in the issue's comments.
- **Requirements, shown only when found.** They never change a repo's score, and each quotes the sentence it matched:
  - a **CLA** to sign;
  - a **DCO sign-off** on every commit;
  - an **AI-contribution policy**, matched only on whole-word phrases near contribution words.
- **Local setup**, for information only: easy (Docker, compose or a devcontainer) / documented / unclear.

## 11. The LLM (M2)

**Jobs:**
1. Write "why it matters" and up to 3 first steps for the top `max_candidates`.
2. Give a second opinion on repos where the classifier's confidence is between 0.4 and 0.7, and on every reported repo.

**Review schema:** `{project_type, api_style, confidence, evidence, why, first_steps}`.
- The API type decides whether the LLM agrees with it. For example, a REST check plus an LLM answer of "GraphQL" counts as disagreement.
- Disagreement lowers confidence in proportion to the LLM's certainty.
- Agreement can raise confidence to at most 0.8.
- The LLM never sees repos that failed the gate.

**Backends:** both done ✅.
- Ollama: JSON schema output, `think: false`, the model kept loaded during the batch, then unloaded.
- Any OpenAI-compatible API, falling back to JSON mode if a provider doesn't support schemas.

**M2 tuning:** `bench-llm` sets `max_candidates`. The labeled CSV checks the LLM's second opinions, and if it doesn't help, the prompt or model is tuned. The LLM stays on either way.

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

**Quiet days:**
- Earlier items still open are re-checked.
- If there's still nothing new, no file is written and no notification sent; `docscout status` shows why.
- After 7 empty days, one "pool running dry" notification.

**Failure alerts:** an expired token (401) or 3 failed runs in a row send a "DocScout needs attention" notification.

## 14. Running unattended

| Situation | Behavior |
|---|---|
| Every 15 minutes | `run --if-due` exits in under 1 second unless a run is due **and** the machine is online |
| Online check | `GET /rate_limit`. It doesn't count against the API quota |
| Offline | Logs it and exits; the run stays due and starts at most 15 minutes after reconnecting |
| Interrupted | Each repo or slice is saved as it finishes; the next trigger resumes |
| Rate limited | Waits for the reset time; if that's more than 15 minutes, stops and resumes later |
| LLM unavailable | The report uses code-based results and says "LLM review skipped" |

`docscout schedule install|uninstall|status [--dry-run]`:
- **Linux (M3, by the deadline):** a systemd user service and timer: `OnStartupSec=2min`, `OnCalendar=*:0/15`, `Persistent=true`, `Nice=10`.
- **macOS (M5, after the deadline):** a LaunchAgent with `RunAtLoad` plus `StartCalendarInterval` at minutes 0/15/30/45, so runs missed during sleep happen on wake. Loaded with `launchctl bootstrap gui/<uid>`, with absolute paths.
- **Windows (M5, after the deadline):** Task Scheduler XML with one repeating 15-minute `TimeTrigger`, plus:
  - `StartWhenAvailable=true`;
  - `DisallowStartIfOnBatteries=false` and `StopIfGoingOnBatteries=false`;
  - `MultipleInstancesPolicy=IgnoreNew` and `InteractiveToken`.

  It runs the windowless `docscout-bg` entry point, and every subprocess uses `CREATE_NO_WINDOW`.

## 15. Data model (M1: SQLite, versioned with `PRAGMA user_version`)

- `repos(full_name PK, source, stars, language, language_match, license, pushed_at, head_sha, api_type, type_conf, status[new|reported|ignored|done], ignore_reason, first_seen, last_checked, next_check)`
- `findings(repo, run_id, api_type, kind, gap, health, score, effort, flags_json, details_json)`
- `pr_stats(repo PK, outsider_merged_180d, merge_rate, median_ttm_days, docs_prs_merged, committers_90d, fetched_at)`
- `issues(url PK, repo, number, title, labels, outreach, author_assoc, claimed, state, first_seen, last_checked)`
- `queue(repo PK, priority, source, enqueued_at)`, `sweep_cursor(slice_key PK, page, cycle, done_at)` and `seed_meta(source PK, fetched_at)`
- `runs(id, started, finished, status[ok|offline|partial|empty|failed], analyzed, new_items, api_calls, error)` and `llm_reviews(repo, provider, model, seconds, review_json, created)`

## 16. Code layout

✅ = exists today.
```
hacktoberfest/
  pyproject.toml ✅  LICENSE ✅  README.md ✅  docs/PLAN.md ✅  .github/workflows/ci.yml (M5: 3 OS × py3.11, 3.13)
  docscout/
    cli.py ✅          # init set profile discover eval bench-llm ✅ · run score ignore done status (M1) · schedule doctor (M3)
    config.py ✅  profile.py ✅  languages.py ✅  setup_wizard.py ✅  errors.py ✅  safe_yaml.py ✅
    github.py ✅  health.py ✅  classify.py ✅  evidence.py ✅  discover.py ✅  evaluate.py ✅  bench.py ✅
    apitypes/ base.py ✅ rest.py ✅          # + spec scoring for REST (M1); graphql.py, grpc.py, … (later)
    sources/ awesome_selfhosted ✅ repo_search ✅ help_requested ✅ code_search ✅
    analyze/ tree.py ✅  prose.py · elsewhere.py · checks.py (M1)
    llm/ base.py ✅ ollama.py ✅ openai_compat.py ✅
    db.py · scoring.py · report.py · sanitize.py (M1)    lock.py · netcheck.py · notify.py · scheduler/linux.py (M3)
    scheduler/macos.py · scheduler/windows.py (M5)    safe_fetch.py (M4)
  tests/ ✅ 81 tests · fixtures/labeled_repos.csv (after M0 check)
```

## 17. Risks

| Risk | Mitigation |
|---|---|
| **Deadline (one week)** | M3 before M2; "if time allows" items cut first; M4 and M5 after the deadline |
| Discovery accuracy is low (**confirmed** for topic search) | Curated seed, per-source accuracy check in M0, classifier, health gate |
| Noisy help requests (**confirmed**) | Outreach-label or outside-author rule, deny lists, health gate |
| The local LLM is too slow on 7.6 GB of RAM (1.6 GB free on 12 Oct; the model is 4.6 GB) | `bench-llm` with apps closed; hosted or `none` as fallback; every LLM setup problem is reported with its fix, and the report works without the LLM ✅ |
| A temporary GitHub error ends a long run (**seen** on 12 Oct: one 404 crashed `discover`) | One retry on short-lived 404s; a failing repo is skipped and recorded; Ctrl+C keeps partial results ✅ |
| A PR edits a generated spec | Generated-spec check redirects the suggestion to code annotations |
| Wasted effort (already claimed, CLA, AI policy) | Claim check and requirement badges on the top 10 |
| Prompt injection pushes a repo up the ranking | Confidence raise capped at 0.8; code-only gates; sanitized output |
| A malicious repo targets your machine | Alias-free YAML, in-memory archives, fixed notification text, sanitized report, safe fetcher (M4) |
| The token expires and runs fail silently | 401 alert; alert after 3 failed runs |
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
  - offline: logs it, then runs once you reconnect;
  - Ctrl+C resumes; `kill -9` doesn't leave runs blocked;
  - an invalid token sends an alert;
  - a quiet day writes no file;
  - 3 days (Fri 16 – Mon 19) with no manual starts; 7 days after the deadline.
- **M5:** a fresh `pipx` install on a Mac and a Windows machine works, including on battery and after sleep; CI is green on 3 operating systems.

## 19. Later (after M5)

Pre-contribution message drafts; learning from merged or rejected PRs; running the LLM only when plugged in or idle; new API types (GraphQL, gRPC, AsyncAPI, OpenRPC, library/SDK docs via help requests); Up For Grabs as a seed; GitLab and Codeberg; a dashboard; Spectral lint; standalone executables.
