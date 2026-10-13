# DocScout

Finds open-source projects that serve an API, have documentation gaps you can fix, and are likely to accept your pull request. It starts with REST APIs, and is built so other API types (GraphQL, gRPC, AsyncAPI, ...) can be added as modules. Everything it checks is language- and framework-agnostic.

**How it works:** code searches GitHub, checks each project's health and measures its docs gaps. Then **an open-weight model (Gemma 4, running locally with Ollama) reviews every project that passes**. It decides whether the project really has an API worth documenting, explains why its docs matter, and suggests where to start. Only projects it has reviewed are reported.

> **Status:** works on Linux, including daily runs without starting it yourself. macOS and Windows come later.

## Install

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Set up

```bash
.venv/bin/docscout init
```

`init` asks at most 3 questions, and usually fewer:

| Question | When it's asked |
|---|---|
| What do you want to document? | Only when there's more than one API type. REST is the only one today, so this is skipped |
| Which model reviews projects? Local (Ollama, Gemma) or hosted (an open-weight model through an OpenAI-compatible API such as OpenRouter or Groq) | Always, unless you pass `--llm`. Choosing hosted adds a model name and an API key |
| GitHub token | Only if none is set yet. Without one, GitHub allows 60 requests an hour, enough for about 10 repos. [Create one](https://github.com/settings/personal-access-tokens/new) with **Public repositories (read-only)** access |

Everything else starts with a default. `init` tests the token with GitHub and doesn't save a rejected one. It also checks that the Ollama model is installed. `docscout profile` shows your settings in plain words.

**No Ollama, or the model isn't downloaded yet?**
- `init` shows the status next to the local option;
- `bench-llm` and the daily run say exactly what to run, for example `ollama pull gemma4:e2b`;
- DocScout still searches and checks projects, but they wait for a review and nothing is reported until the model is available.

Install Ollama from [ollama.com](https://ollama.com), or use a hosted model with `docscout set --llm openai_compatible`.

### Changing other settings

`docscout set` changes settings without asking any questions:

```bash
.venv/bin/docscout set --languages "python, go" --sizes small,medium
```

| Setting | Default | Flag |
|---|---|---|
| Languages you know | any | `--languages "python, go"`. Short names like `py`, `ts`, `golang` and `c#` work. `any` clears the list |
| Exclude other languages | no. For REST, other languages are kept and yours rank higher, since most fixes are YAML or Markdown edits. Library/SDK docs, once added, always require your language | `--only-these-languages` |
| Project sizes | small, medium, large | `--sizes small,medium`. The sizes are small (20–200★), medium (200–1,000★), large (1,000–5,000★) and huge (5,000★ and up) |
| Model provider | local Ollama | `--llm ollama` or `--llm openai_compatible` |
| Model | `gemma4:e2b` | `--model NAME` |
| Hosted model address | OpenRouter | `--base-url https://api.groq.com/openai/v1` (any OpenAI-compatible API) |
| Notifications for the daily run | on | `--start-notification off`, `--finish-notification off` |

Three model settings live in the `[llm]` section of `config.toml`:
- `reviews_per_run`: 13 a day, about 10 minutes at 45 s each. `docscout bench-llm` measures your speed.
- `think`: `off`, `borderline` (only where the code is unsure) or `on`. Slower.
- `min_free_memory_gb`: 2.5. A local model waits until this much memory is free, so your computer doesn't start swapping.

The same flags work on `discover` for a single run without saving, for example `docscout discover --languages rust --only-these-languages`. `init` also accepts them; any setting given as a flag skips its question.

Settings are saved in `config.toml` and secrets in `secrets.env`, both in your config folder (`~/.config/docscout/` on Linux). `secrets.env` is readable only by you. You can also set the token or the LLM API key with the `GITHUB_TOKEN` or `DOCSCOUT_LLM_API_KEY` environment variables, which take precedence.

## Find projects to contribute to

```bash
.venv/bin/docscout run              # checks up to 60 repos, Gemma reviews up to 13 (about 20 minutes), writes a report
.venv/bin/docscout run --limit 10   # a quicker, smaller run
```

**The report** goes to `~/Documents/DocScout/reports/` (set `[report] dir` to change it):
- every run writes a new dated file, such as `2026-10-14.md`, then `2026-10-14_2.md` for a second run that day, and `latest.md` is always a copy of the newest;
- a run that finds nothing new writes no file.

**Each item shows:**
- **Gemma's review:** what the project is (for example "an app or service with its own REST API"), the quote it based that on, and how it changed the code's confidence (for example 0.50 → 0.80). It can raise confidence to at most 0.8, so a README written to fool it can't push a project to the top;
- **why its docs matter** and **up to 3 first steps**, from Gemma;
- **the gap:** for an OpenAPI spec, which operations lack descriptions, examples, success schemas or error responses, with a permanent link to the file; for prose docs, which endpoints lack a description, request and response examples, status codes or auth;
- **the project's health:** stars, last push, and how many outside pull requests it merged recently and how fast;
- **"Maintainers asked for help"** with links, when the project has open docs issues labeled "help wanted" or "good first issue";
- **"Before you start":** an open docs PR or someone already offering to do the work, a CLA, DCO sign-off, or an AI-contribution policy (quoted), and how easy it is to run locally;
- **"Check manually"** when the docs may live elsewhere (a docs website, a separate docs repo, or Swagger UI served by the running app). DocScout can't read those yet, so it reports these only when maintainers asked for help.

**Once you've picked a project,** let Gemma draft your first message to the maintainers:

```bash
.venv/bin/docscout draft owner/repo
```

It writes a short message asking whether a docs PR would be welcome, naming the gaps DocScout found. It replies on the open "help wanted" or docs issue if there is one, otherwise it drafts a new issue. It checks again that nobody has started on it. Edit it so it sounds like you, then post it yourself: DocScout never posts anything.

**Once you've dealt with a project,** hide it from future reports:

```bash
.venv/bin/docscout done owner/repo                     # you contributed
.venv/bin/docscout ignore owner/repo --reason "..."    # not for you; the reason helps tune DocScout
```

Repos are only checked again after 90 days (`[discovery] recheck_after_days`), and reported ones stay listed under "Still open from earlier" until you mark them.

**To look at one spec, docs file or repo:**

```bash
.venv/bin/docscout score path/to/openapi.yaml   # gap score with the reason for each point
.venv/bin/docscout score docs/API.md            # endpoint completeness of a Markdown file
.venv/bin/docscout score owner/repo             # the full check with Gemma's review, as it would appear in a report
```

## Run it every day by itself (Linux)

```bash
.venv/bin/docscout schedule install   # once
.venv/bin/docscout status             # any time: today's progress, the schedule and recent runs
```

After that you never start it yourself:
- **Every 15 minutes while you're logged in,** DocScout checks whether today's run is due. If it isn't, it exits within a second.
- **Once a day** it checks up to `daily_repo_budget` repos (60 by default) and writes a report. A notification says when it starts ("your computer may be slower for about N minutes") and when it finishes, with where the report is.
- **After a restart,** the first check is 2 minutes after you log in.
- **When you're offline,** it waits, and starts within 15 minutes of the connection coming back. If the connection drops during a run, the run pauses and continues later, without checking anything twice.
- **If the computer shuts down mid-run,** the next check continues the run, and anything already found still goes into the report.
- **When memory is low,** Gemma waits instead of slowing your computer down. The projects found are held, and a later check reviews them once enough memory is free. You get a notification saying how many are waiting.
- **Problems that need you** (no GitHub token, an expired token, three failed runs in a row, broken settings, Gemma unable to review for 2 days) always get a notification, at most once a day each.
- **A week without anything new** gets one notification suggesting a wider search.
- It runs at low priority, so the computer stays responsive.

Running `docscout run` yourself counts toward the day: the scheduled run then only checks what's left of the day's budget. Only one run happens at a time.

**To turn notifications off:**

```bash
.venv/bin/docscout set --start-notification off    # or --finish-notification off; "on" turns them back on
```

Problem notifications can't be turned off.

**To stop daily runs:** `docscout schedule uninstall`. Your reports and history are kept. Add `--dry-run` to `install` or `uninstall` to see the changes without making them.

**The log:** `journalctl --user -u docscout.service -n 50`.

On macOS and Windows, daily runs come in a later version (stage M5). Until then, run `docscout run` yourself.

## Stage M0: check the tool finds the right projects

```bash
# 0. Set up (once; at most 3 questions). Paste your GitHub token when asked.
.venv/bin/docscout init

# 1. Draw about 60 repos that pass the health checks, split across the discovery sources
#    (~300-400 API calls, about 5-15 minutes; --seed makes the sample reproducible)
.venv/bin/docscout discover --sample 60 --csv sample.csv --seed 1

# 2. Open sample.csv and fill the "label" column for each row with one of:
#    serves_api | api_tooling | library | spam | other

# 3. Measure accuracy, overall and per source
.venv/bin/docscout eval sample.csv

# 4. Measure LLM speed and memory on this machine (close memory-hungry apps first)
.venv/bin/docscout bench-llm
```

**Done when:** at least 70% of the repos the classifier calls `serves_api` really are. If a source is below 50%, remove it from `[discovery] sources`.

**After changing the classifier,** re-run it on labeled repos and compare:

```bash
.venv/bin/docscout eval tests/fixtures/labeled_repos.csv --reclassify
```

The first run fetches each repo's details and caches them in your data folder; later runs make no API calls. It prints the new accuracy and every prediction that changed ("now right", "now wrong" or "still wrong").

**To measure Gemma's review** on the same labeled repos (close other apps first; about 45 s per repo on a small laptop):

```bash
.venv/bin/docscout eval tests/fixtures/labeled_repos.csv --llm                   # thinking off
.venv/bin/docscout eval tests/fixtures/labeled_repos.csv --llm --think borderline   # thinking on where the code is unsure
```

It prints precision and recall with and without Gemma, what Gemma changed, the time per review, and the memory Gemma used, with a suggested `min_free_memory_gb`. Reviews are cached, so the second command only reviews the borderline repos again. Ctrl+C stops it, and the same command continues.

### Labeling guide

Give each row about a minute. Open the `url`, read the description and the top of the README, then fill in `label`:

| Label | Meaning | Examples |
|---|---|---|
| `serves_api` | An app or service that exposes its own REST/HTTP API, even if it's poorly documented | a self-hosted tracker, a CMS, a monitoring server, a backend with `/api/...` routes |
| `api_tooling` | A tool for working with APIs, or a framework for building them | code generators, validators, mock servers, test tools, web frameworks, MCP servers that wrap other APIs |
| `library` | Code you import | SDKs, API clients, wrappers |
| `spam` | Promotional or keyword-stuffed repos | "Free … API 2026, 0% fee" |
| `other` | Anything else | CLIs, desktop apps with no HTTP API, games, dotfiles |

**Edge cases:**
- **It serves an API, but GraphQL- or gRPC-only:** `other`, with `graphql` or `grpc` in the `note` column. (Only REST is enabled today.)
- **A database or server with an HTTP API alongside other protocols:** `serves_api`.
- **An app with no API at all** (you install it and use its web or desktop interface, nothing else): `other`. It may have docs worth improving, but not API docs.
- **An app whose only API is in code** (classes and methods you call from plugins or extensions, like the PHP API of the MODX CMS): `other`, with `library API` in `note`. It's a candidate for the future library/SDK docs type, not for REST.
- **An official REST API that's part of the project itself, even an undocumented one:** `serves_api`. If REST is only available through third-party add-ons, use `other`.
- **Label by what the project mainly is,** not by what DocScout predicted.
- **Can't tell after 2 minutes:** pick your best guess and write `unsure` in `note`.
- **It looks like a good place to contribute:** say so in `note`. It doesn't affect scoring, but helps later.

**Save carefully:**
- Leave every other column untouched.
- Keep it as CSV (comma-separated, UTF-8). In LibreOffice Calc: *File → Save As → Text CSV → Keep current format*.
- `eval` ignores rows with an empty label, so you can stop part-way and come back later.

## How it finds projects

| Source | What it is |
|---|---|
| `awesome_selfhosted` | The curated [awesome-selfhosted](https://github.com/awesome-selfhosted/awesome-selfhosted-data) list of real self-hosted apps |
| `repo_search` | GitHub repo search, using each enabled API type's `repo_queries` |
| `help_requested` | Open, unassigned issues where maintainers ask for API docs help. An issue only counts if it carries a "help wanted" or "good first issue" label, or was opened by someone outside the project. Bots, dependency dashboards and bounty labels are ignored |
| `code_search` (optional, needs a token) | Repos containing an API definition file, using each API type's `definition_filenames` |

Every repo, whatever its source, goes through the same code-only health gate: not archived or a fork, has a license, at least 20 stars, recent pushes, and real activity. When a maintainer has labeled a docs issue "help wanted" or "good first issue", the activity part is looser (`[health.help_requested]`): the explicit ask stands in for a history of merged outside PRs.

## API types

Everything specific to one kind of API lives in its own module under [docscout/apitypes/](docscout/apitypes/). Only `rest` exists today:

```toml
[api_types]
enabled = ["rest"]
```

Each API type supplies:
- its search settings, in its `[api_types.<key>]` config section: `repo_queries`, `definition_filenames` and `issue_keywords`;
- `definition_pattern`: what its definition files are called, for example OpenAPI specs or `.graphql` schemas;
- `evidence()`: the text and file-name signals that a repo exposes this kind of API;
- `llm_style`: the API style the LLM reports for it.

Discovery, the health gate, ranking and the LLM backends are shared. To add a type:
1. Subclass `ApiType`.
2. Register it in `docscout/apitypes/__init__.py`.
3. Add its config section.
4. Check it on its own labeled sample (`discover`, then `eval`) before enabling it by default.

`tests/test_apitypes.py` shows a minimal GraphQL type wired in this way.

## Configuration

Most people only need `docscout init` and `docscout set`, which write the `[profile]` and `[llm]` sections. Every other setting has a default in [docscout/default_config.toml](docscout/default_config.toml), such as search queries, health thresholds and the daily budget. To change one, add the key to your own `config.toml`, or pass `--config path/to/config.toml`.

To switch to a hosted model, set `provider = "openai_compatible"` together with `base_url`, `model` and the `DOCSCOUT_LLM_API_KEY` secret. Any OpenAI-compatible API works, for example OpenRouter, Groq, Together or OpenAI.

## Development

```bash
.venv/bin/pytest
```

## Credits

The curated seed list comes from [awesome-selfhosted-data](https://github.com/awesome-selfhosted/awesome-selfhosted-data) (CC-BY-SA 3.0).
