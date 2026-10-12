# DocScout

Finds open-source projects that serve an API, have documentation gaps you can fix, and are likely to accept your pull request. It starts with REST APIs, and is built so other API types (GraphQL, gRPC, AsyncAPI, ...) can be added as modules. Everything it checks is language- and framework-agnostic.

> **Status: stage M0 (prove discovery).** This stage checks that DocScout finds the right projects before anything else is built on top. The daily report, scheduling and cross-platform setup come in later stages.

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
| Which LLM? Local Ollama, hosted, or none | Always, unless you pass `--llm`. Choosing hosted adds a model name and an API key |
| GitHub token | Only if none is set yet. Without one, GitHub allows 60 requests an hour, enough for about 10 repos. [Create one](https://github.com/settings/personal-access-tokens/new) with **Public repositories (read-only)** access |

Everything else starts with a default. `init` tests the token with GitHub and doesn't save a rejected one. It also checks that the Ollama model is installed. `docscout profile` shows your settings in plain words.

**No Ollama, or the model isn't downloaded yet?** Everything except the LLM step still works:
- `init` shows the status next to the local option;
- `bench-llm` and the daily report say exactly what to run, for example `ollama pull gemma4:e2b`;
- reports fall back to code-based results.

Install Ollama from [ollama.com](https://ollama.com), or switch with `docscout set --llm openai_compatible` or `--llm none`.

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
| LLM provider | local Ollama | `--llm ollama`, `--llm openai_compatible` or `--llm none` |
| LLM model | `gemma4:e2b` | `--model NAME` |
| Hosted LLM address | OpenRouter | `--base-url https://api.groq.com/openai/v1` (any OpenAI-compatible API) |

The same flags work on `discover` for a single run without saving, for example `docscout discover --languages rust --only-these-languages`. `init` also accepts them; any setting given as a flag skips its question.

Settings are saved in `config.toml` and secrets in `secrets.env`, both in your config folder (`~/.config/docscout/` on Linux). `secrets.env` is readable only by you. You can also set the token or the LLM API key with the `GITHUB_TOKEN` or `DOCSCOUT_LLM_API_KEY` environment variables, which take precedence.

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

**Done when:** at least 70% of the repos the classifier calls `serves_api` really are. If a source is below 50%, remove it from `[discovery] sources`. The labeled CSV then becomes a regression test.

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
