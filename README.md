# DocScout

Struggling to find open-source API docs to contribute to? Digging through dozens of GitHub repos for the one project that fits?

DocScout finds projects that serve a REST API, are actively maintained, have documentation gaps you can fix, and are likely to accept your pull request. It checks new projects every day and gives you a short, ranked list, with each gap counted and linked.

Use it on the [website](https://docscout-web.onrender.com/), run it yourself [once](#run-it-once) or [every day by itself on Linux](#run-it-every-day-by-itself-linux), or give [the skill](#use-it-from-your-own-ai-agent) to your own AI agent.

**How it works:** code searches GitHub, checks each project's health and measures its docs gaps. Then **an open-weight model, Gemma 4, reviews every project that passes**. It decides whether the project really has an API worth documenting, checks that each maintainer's help request asks for the work DocScout found, reads the issue comments for anyone who has offered to do that work, explains why the docs matter, and suggests where to start. Open pull requests that change the docs are measured by code, so a PR claims only the gaps it actually fixes. Only projects Gemma has reviewed are reported. Gemma runs on your computer with Ollama, or through a hosted API, as on the website (Gemma 4 31B). DocScout starts with REST APIs and is built so other API types (GraphQL, gRPC, AsyncAPI, ...) can be added as modules; everything it checks is language- and framework-agnostic.

> **Status:** works on Linux, including daily runs without starting it yourself. macOS and Windows come later.

## The website

[docscout-web.onrender.com](https://docscout-web.onrender.com/) runs DocScout for you, with Gemma 4 31B on Google's API, so there's nothing to install.

- **Every open pick stays listed,** and is checked every 6 hours for new pull requests, offers in comments, closed help requests and changes to its docs. A pick's docs are measured again when its docs file changes, and at least once a week.
- **A pick leaves the list** when:
  - its docs are fixed, with fewer than 5 operations or endpoints still needing work;
  - the project goes quiet: archived, no push in 60 days, or it fails the other health checks;
  - its docs may live elsewhere and no maintainer has asked for help with them;
  - the repo is deleted.

  A renamed repo keeps its pick under the new name.
- **Each card** says when the pick was found and last checked, what needs doing, and whether anyone is already on part of it ("Partly claimed", with the work that's left).
- **Free:** the best 3 found this week. **Subscribers ($2 a month):** every open pick, best first or newest first, with filters for the size of the job and for projects whose maintainers asked for help.
- **Search** by what a project is about: "ai", "payments", "go". It looks through each pick's name, description, GitHub topics and language. A word for a kind of project also finds the words those projects use, so "ai" finds projects tagged `llm` or `rag`. Every word must match. Visitors see how many picks match and the free ones among them; subscribers see them all.

Before you start on a pick, comment on the issue, or open one, so the next writer, and DocScout, can see you're on it.

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
- `reviews_per_run`: 11 a day, about 10 minutes at 51 s each. `docscout bench-llm` measures your speed.
- `think`: `off`, `borderline` (only where the code is unsure) or `on`. Slower.
- `min_free_memory_gb`: 6, since `gemma4:e2b` used 5.5–5.9 GB. A local model waits until this much memory is free, so your computer doesn't start swapping.

The same flags work on `discover` for a single run without saving, for example `docscout discover --languages rust --only-these-languages`. `init` also accepts them; any setting given as a flag skips its question.

Settings are saved in `config.toml` and secrets in `secrets.env`, both in your config folder (`~/.config/docscout/` on Linux). `secrets.env` is readable only by you. You can also set the token or the LLM API key with the `GITHUB_TOKEN` or `DOCSCOUT_LLM_API_KEY` environment variables, which take precedence.

## Run it yourself

Two ways, both after [installing](#install) and [setting up](#set-up). Both write the same [report](#read-the-report).

| | Command | What happens |
|---|---|---|
| **Run it once**, whenever you want | `docscout run` | Checks up to 60 projects, Gemma reviews the promising ones, and a report is written. About 15 minutes |
| **Run it every day by itself** (Linux) | `docscout schedule install`, once | A run starts on its own each day in the background, and a notification tells you when the report is ready |

### Run it once

```bash
.venv/bin/docscout run              # checks up to 60 repos, Gemma reviews up to 11 (about 15 minutes), writes a report
.venv/bin/docscout run --limit 10   # a quicker, smaller run
.venv/bin/docscout run --limit 0    # only Gemma's reviews of projects still waiting for one (e.g. after a run with too little free memory)
```

### Run it every day by itself (Linux)

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

## Read the report

Reports go to `~/Documents/DocScout/reports/` (set `[report] dir` to change it):
- every run writes a new dated file, such as `2026-10-14.md`, then `2026-10-14_2.md` for a second run that day, and `latest.md` is always a copy of the newest;
- a run that finds nothing new writes no file.

**Each item shows:**
- **Gemma's review:** what the project is (for example "an app or service with its own REST API"), the quote it based that on, and how it changed the code's confidence (for example 0.50 → 0.80). It can raise confidence to at most 0.8, so a README written to fool it can't push a project to the top;
- **why its docs matter** and **up to 3 first steps**, from Gemma;
- **the gap,** with a permanent link to the file:
  - for an OpenAPI spec: the operations with no description, with parameters that have no description, with no request example (of those that take a request body), with no example of a successful response (of those that return something), with no success schema, or whose error responses don't describe their body; and the fields a reader sends or gets back that have no description. Examples count only where they show the call, on a request body or a successful response: one example on a shared error response doesn't make every operation documented;
  - for prose docs: the endpoints with no description, request or response example, status codes or auth.

  Specs are found by name (`openapi.yaml`, `swagger.json`), by folder (`docs/openapi/…`), and as files named like `api.yaml`. A spec inside a client that openapi-generator wrote (a folder holding `.openapi-generator/`), or at the top of that client's package, describes an API the client calls, often another service's, so it's measured only when the repo has no other spec;
- **"Docs published":** where the docs can be read as pages without installing the project: a docs site built from the repo (MkDocs, Sphinx, Docusaurus, Mintlify…), a docs website, a separate docs repo, or Markdown API docs on GitHub. These projects rank higher (`[scoring] published_docs_bonus`), because you can see the gap in a browser and the fix is Markdown;
- **the project's health:** stars, last push, and how many outside pull requests it merged recently and how fast;
- **"Maintainers asked for help"** with links, when maintainers have an open issue asking for the work DocScout found. Gemma reads each request next to the gap and quotes the line its answer rests on, and code checks the quote is really in the issue. A request for other API-docs work is listed as related, and one that isn't about API docs isn't shown. Only a request for this work raises the score;
- **"Before you start":** whether someone is already on the gap, a CLA, DCO sign-off, or an AI-contribution policy (quoted), and how easy it is to run locally. Claims are checked one gap at a time:
  - **An open pull request that changes the measured docs file is measured:** the file in the PR against the version it started from. It claims only the operations it fixes, so a feature PR that edits the spec for its own changes claims nothing. On a generated spec, where the fix belongs in code annotations, Gemma judges the PR instead.
  - **Comments are Gemma's call,** on help requests that ask for this work. An offer counts for 30 days from the person's last comment; an older one is shown as an offer to ask about. Once the person opens a PR for the issue (one that names or links it), the PR is measured instead.
  - **A project goes below the rest** only when fewer than 5 operations or endpoints are left unclaimed. Otherwise it shows "Partly claimed", one line per claim, and the work left.

  For 7 days after a project is reported, each run checks it again once a day (`[checks] recheck_claims_days`), and "Still open from earlier" shows ⚠️ when someone may be on it;
- **"Check manually"** when the docs may live elsewhere (a docs website, a separate docs repo, or Swagger UI served by the running app). DocScout can't read those yet, so it reports these only when maintainers asked for help.

**Small gaps are skipped:** a project is reported only when at least 5 operations or endpoints need work (`[report] min_effort_units`). One undocumented endpoint is a quick fix, not a project to contribute to. A skipped project is checked again after 90 days, in case its API grows.

## Once you've picked a project

Let Gemma draft your first message to the maintainers:

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

## Use it from your own AI agent

If you'd rather ask an AI agent such as Claude Code, the same method is available as a skill: [skills/find-api-docs-to-contribute/SKILL.md](skills/find-api-docs-to-contribute/SKILL.md). It tells the agent where to look, how to check a project will merge outside help, how to count the gaps in a spec or in prose docs, and what does and doesn't count as someone already working on them.

**Install it for Claude Code** (for all your projects):

```bash
mkdir -p ~/.claude/skills/find-api-docs-to-contribute
curl -fsSL https://raw.githubusercontent.com/Tammibriggs/doc-scout/main/skills/find-api-docs-to-contribute/SKILL.md \
  -o ~/.claude/skills/find-api-docs-to-contribute/SKILL.md
```

Then ask, for example, "Find me open-source API docs I could contribute to", or type `/find-api-docs-to-contribute`. To use it in a single project instead, put the folder in that project's `.claude/skills/`. The skill follows the open [Agent Skills](https://agentskills.io) format, so other agents that support it can use the same folder.

The agent needs the GitHub API: the GitHub CLI logged in (`gh auth login`), or a token in `GITHUB_TOKEN`.

**DocScout or the skill?** In the comparison ([results](docs/comparison/RESULTS.md), round 2), an agent with an earlier version of this skill found twice as many projects worth acting on (6 against 3) and got more of its gap claims right (96% against 81%). DocScout's picks were worth acting on more often (3 of 4, against 6 of 10), and it took 8.5 minutes and no tokens, where the agent took 46 minutes and about 324,000 tokens. DocScout runs every day by itself; the agent searches when you ask.

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

**To measure Gemma's help-request and claim answers** on the labeled test set in [tests/fixtures/m6/](tests/fixtures/m6/) (live; about 53 s a question on Google's free tier):

```bash
.venv/bin/docscout eval-claims                 # both
.venv/bin/docscout eval-claims --part help     # only whether each help request asks for the work found
```

It lists each case with your label and Gemma's answer, marks the ones that disagree, and prints the time per question.

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
| `help_requested` | Open, unassigned issues where maintainers ask for API docs help. An issue only counts if it's about docs (a docs label, or a title such as "Document the webhooks") and carries a "help wanted" or "good first issue" label or was opened by someone outside the project. Bots, dependency dashboards, bounty labels and bounty programs (such as Stellar Wave, whose issues collect applications for points) are ignored, and so are bug reports (titles such as "bug(api): …" or "[Bug] …"), which ask for a code fix even when they compare the API with its docs. Gemma then reads each issue: only one that asks for the work DocScout found earns the score bonus and the looser activity check below |
| `code_search` (needs a token; on the website since 10 Nov) | Repos containing an API definition file (`openapi.yaml`, `swagger.json`, …), using each API type's `definition_filenames`, sliced by file size. GitHub returns at most 1,000 results per search, so a size band with more is split in two, and again, until each band can be read to its end; runs work through the bands in turn (`code_search_per_run` a run), each continuing from the page it reached. Most repos it finds are small or unlicensed, so each page's repos are looked up together in one GraphQL request, and those failing the cheap checks are turned away without counting toward `daily_repo_budget` |

Every repo, whatever its source, goes through the same code-only health gate: not archived or a fork, has a license, at least 20 stars, recent pushes, and real activity. When a maintainer has labeled a docs issue "help wanted" or "good first issue", the activity part is looser (`[health.help_requested]`): the explicit ask stands in for a history of merged outside PRs. If Gemma then finds the issue doesn't ask for the work DocScout found, the project must pass the normal thresholds.

## API types

Everything specific to one kind of API lives in its own module under [docscout/analyze/apitypes/](docscout/analyze/apitypes/). Only `rest` exists today:

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
2. Register it in `docscout/analyze/apitypes/__init__.py`.
3. Add its config section.
4. Check it on its own labeled sample (`discover`, then `eval`) before enabling it by default.

`tests/test_apitypes.py` shows a minimal GraphQL type wired in this way.

## Configuration

Most people only need `docscout init` and `docscout set`, which write the `[profile]` and `[llm]` sections. Every other setting has a default in [docscout/settings/default_config.toml](docscout/settings/default_config.toml), such as search queries, health thresholds and the daily budget. To change one, add the key to your own `config.toml`, or pass `--config path/to/config.toml`.

To switch to a hosted model, set `provider = "openai_compatible"` together with `base_url`, `model` and the `DOCSCOUT_LLM_API_KEY` secret. Any OpenAI-compatible API works, for example OpenRouter, Groq, Together or OpenAI. Set `fallback_model` to a second model from the same provider, and DocScout asks it whenever the first can't answer after its retries; the hosted version uses Gemma 4 31B with Gemma 4 26B behind it.

The website's settings are in [deploy/render.toml](deploy/render.toml). `[picks] keep_open = true` keeps open picks listed, and the caps in `[picks]` and `[llm]` limit how many re-checks, claim checks and Gemma questions each run makes. Its job runs every 6 hours: the first run of each day (UTC) is a full `docscout run`, and the others run `docscout look`, which looks at every listed pick and acts on what changed. `DOCSCOUT_ATLAS_DATABASE` points the job, the commands it starts and the website at another Atlas database, for a dry run on a copy.

## How the code is organized

The `docscout` package is grouped by the stages a project goes through, in order:

| Folder | What's in it |
|---|---|
| [`settings/`](docscout/settings/) | Your profile (`init`, `set`), the config loader and the defaults |
| [`find/`](docscout/find/) | Where candidates come from ([`sources/`](docscout/find/sources/)), the GitHub client, the health checks and the classifier |
| [`analyze/`](docscout/analyze/) | Measuring the docs gaps (specs, prose, docs published elsewhere), what an open pull request would fix, the claim and requirement checks, and the score. Each API type lives in [`apitypes/`](docscout/analyze/apitypes/) |
| [`llm/`](docscout/llm/) | Gemma: the local (Ollama) and hosted clients, the review of each project, the help-request and claim questions, and the draft message to maintainers |
| [`run/`](docscout/run/) | One run from start to report, daily runs and their schedule, the database, the lock and notifications; for the website, the look for changes every 6 hours and keeping open picks true |
| [`measure/`](docscout/measure/) | Accuracy checks against the labeled repos (`docscout eval`), Gemma's help-request and claim answers (`docscout eval-claims`), and the model benchmark (`bench-llm`) |
| [`hosted/`](docscout/hosted/) | The hosted version: the website, the daily job on Render, MongoDB Atlas and Stripe |

[`cli.py`](docscout/cli.py) holds every command. [`docs/PLAN.md`](docs/PLAN.md) records the decisions and measurements, and [`docs/comparison/`](docs/comparison/) compares DocScout with an AI agent given a skill.

## Development

```bash
.venv/bin/pytest                     # the hosted version's tests run when its extras are installed:
.venv/bin/pip install -e ".[dev,hosted]"
```

## Credits

The curated seed list comes from [awesome-selfhosted-data](https://github.com/awesome-selfhosted/awesome-selfhosted-data) (CC-BY-SA 3.0).
