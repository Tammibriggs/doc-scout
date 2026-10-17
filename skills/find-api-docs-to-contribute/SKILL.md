---
name: find-api-docs-to-contribute
description: Find open-source projects that serve a REST API, have measurable gaps in their API documentation, and are likely to merge a docs pull request from a newcomer, with the gaps counted and linked. Use when a technical writer or developer asks for API documentation they could contribute to, open-source docs work to pick up, or a project for a first docs pull request.
license: MIT
compatibility: Needs shell access and the GitHub API, through the GitHub CLI (`gh`, logged in) or a GitHub token in GITHUB_TOKEN.
---

# Find API docs to contribute to

You're helping a technical writer find open-source projects where a documentation pull request would be welcome and useful. Every pick must meet all three conditions:

1. **It serves a REST API:** a running app or service that exposes HTTP endpoints to its users, such as a self-hosted app, a server or a platform. Rule out API clients, SDKs, wrappers, code generators, spec validators, frameworks or libraries for building APIs, CLIs and lists of links. Docker or compose files and words like "self-hosted", "server" or "dashboard" point to an app.
2. **Its API docs have a real gap** that you can show with numbers and links, and that's big enough to be worth a contribution (see "Too small").
3. **It's likely to accept a pull request from an outsider.**

**Rank higher the projects whose docs are published as pages** that can be read without installing the project:
- a docs website, often built from the repo with MkDocs, Sphinx, Docusaurus or Mintlify;
- a separate docs repo;
- API docs in the README or in Markdown files on GitHub.

Rank lower the projects whose API reference appears only in the running app (Swagger UI served by the app). The writer would have to install the app to see the docs, and the fix often means editing code annotations.

## Before you start

If the user hasn't said, use these defaults and say you did:
- projects with 20 to 5,000 stars;
- any programming language, ranking the user's languages higher if they name some;
- up to 5 picks.

## Tools

- **The GitHub API:** prefer the GitHub CLI if it's installed and logged in (`gh auth status`):
  - `gh api repos/OWNER/REPO`
  - `gh api 'search/repositories?q=...'`
  - `gh api graphql -f query='...'`

  Otherwise use `curl` with `-H "Authorization: Bearer $GITHUB_TOKEN"`. Without a token GitHub allows only 60 requests an hour, which isn't enough; ask the user for one (a fine-grained token with public read-only access is enough). Never print or save the token.
- The search API allows 30 requests a minute.
- REST lists of pull requests and commits are large (about 19 KB per pull request). List them through GraphQL, asking only for the fields you need.
- You may read a project's own homepage, docs site and GitHub wiki.
- Save notes in the current folder as you go, so the work can continue if it's interrupted.

## Where to look (best first)

1. **awesome-selfhosted** ([awesome-selfhosted-data](https://github.com/awesome-selfhosted/awesome-selfhosted-data)): about 1,350 hand-picked self-hosted apps.
   - Each app is one YAML file under `software/`, with a `source_code_url`.
   - It's the best source by far: most entries are real apps, and many have an API.
   - The contents API stops listing a folder at 1,000 entries. Download the tarball instead (`gh api repos/awesome-selfhosted/awesome-selfhosted-data/tarball > a.tgz`) and read it with `tar`.
2. **Repo search:** `topic:self-hosted "rest api" in:readme archived:false fork:false`, with a star range and `pushed:>DATE`.
   - About 2 in 3 results are real apps.
   - Avoid `topic:openapi` and `topic:rest-api`. Their results are mostly generators, validators and SDKs; about 1 in 5 is an app.
3. **Maintainers asking for help:** open, unassigned issues updated in the last 60 days, with one of these label filters:
   - `label:documentation,docs`
   - `label:"help wanted","good first issue"`

   Add one keyword: `api`, `openapi`, `swagger` or `endpoint`.
   - Commas mean "any of". `OR` between labels returns nothing.
   - Ignore bounty labels and dependency dashboards. Also ignore tiny repos where the owner tracks their own to-dos; most help requests are like that.
   - A request counts when an outsider opened it, or when it carries an outreach label (help wanted, good first issue).
   - **Read the issue.** It counts only when it asks for work on the API documentation. A docs label isn't enough: feature requests, bugs and other docs topics (installation, a licence badge, typos) don't count.

Put one keyword in each query; `(openapi OR swagger) in:title` returns tens of thousands of junk results.

## Likely to accept a PR (check this before measuring gaps)

- Not archived, not a fork, has a license, stars within the user's range, and pushed in the last 60 days.
- At least 2 human committers (not bots) in the last 90 days.
- At least 1 pull request from an outsider merged in the last 180 days.
  - An outsider's author association isn't OWNER, MEMBER or COLLABORATOR.
  - Ignore bots and dependency bumps (Dependabot, Renovate).
- Exception: when a maintainer labeled a docs issue "help wanted" or "good first issue", 1 committer and no outside merges are enough.

## Finding the gap (measure, don't guess)

- **An OpenAPI or Swagger spec in the repo.** Use the git tree API with `?recursive=1`, and look for:
  - files named `openapi*` or `swagger*`;
  - any YAML or JSON file in an `openapi/` or `swagger/` folder;
  - files named like `api.yaml` or `public-api.yaml`.

  Open each candidate to confirm it's a spec. Skip vendored copies, tests, examples, and specs with fewer than 3 operations. Then count the operations with:
  - no summary or description;
  - parameters without descriptions;
  - no examples;
  - no 2xx schema;
  - no 4xx or 5xx responses.

  Also check for an `info.description` under 50 characters, security schemes without descriptions, and no servers. Report counts, such as "21/38 operations have no description", with example operations.
- **A generated spec:** the fix belongs in the code annotations it's generated from, so say so. Signs:
  - a "DO NOT EDIT" or "generated" header;
  - a CI job that regenerates the file;
  - a `docs.go` beside `swagger.json` (Go's swag);
  - a framework that exports it (drf-spectacular, FastAPI).
- **No spec:** look for endpoint documentation in the README and `docs/`. For each documented endpoint, check for a description, a request example, a response example, status and error codes, and auth. Report what's missing, with counts. These are **not** endpoints or docs:
  - install and download commands: `curl … | sh`, `curl … | bash`, or URLs on raw.githubusercontent.com, GitHub releases or get.docker.com;
  - files in hidden folders such as `.agents/`, `.claude/` or `.cursor/`, which hold instructions for AI coding agents;
  - design records, audits and proposals.
- **Compare with the code when you can.** Prose docs only show the endpoints they mention. If the routes in the code (a router file, controllers, handlers) include endpoints the docs leave out, the missing endpoints are often the biggest gap. Count them and link the routes file.
- **Docs elsewhere:** before calling docs thin or missing, check:
  - the homepage;
  - docs links in the README, but only addresses that belong to the project or its owner (badges, package registries and a framework's docs don't count);
  - a separate docs or website repo, but only one about this project (not another product from the same owner);
  - the GitHub wiki;
  - whether the app serves Swagger UI, ReDoc or `openapi.json` when it runs.

  If the docs live somewhere you can't read, say "check manually". **Never recommend a project only because you found no docs:** in testing, such a pick had its API docs in a GitHub wiki.
- **Too small:** skip a project when fewer than 5 operations or endpoints need work. One undocumented endpoint is a quick fix, not a project to contribute to.
- An open issue from a maintainer about the API docs is the strongest gap evidence. Link it.

## Before recommending

- **Already claimed?** Read the open pull requests (title, description and changed files) and the comments on the project's docs issues. A project is claimed only when someone is working on, or has offered to do, this gap or a large part of it. These are **not** claims:
  - typo, spelling and broken-link fixes, or correcting one value;
  - dependency updates and pull requests opened by bots;
  - work on other docs: installation guides, badges, licensing, how the docs site is built or deployed;
  - features, bug fixes and refactors;
  - offers on an issue about something other than this gap;
  - pull requests and offers with no activity for more than 3 months.

  When something is a claim, name the PR or comment and say how it overlaps. Rank claimed projects below the rest.
- **Requirements:** a CLA to sign, a DCO sign-off on commits, or an AI-contribution policy. Quote the sentence you found.
- **Local setup:** easy (Docker, compose or a devcontainer), documented, or unclear.

## Output

A ranked list, best first. For each pick:

- the `owner/repo` link, stars, main language and last push;
- **Serves an API because:** one line of evidence;
- **The gap:** the biggest gap first, then the other measured facts, each linked to the file (a permalink with a commit SHA) or the issue;
- **Docs published:** where the docs can be read without installing the project, or "only in the running app";
- **Likely to merge:** outside PRs merged in the last 180 days and committers in the last 90 days;
- **Before you start:** whether it's claimed and by what, any CLA, DCO or AI policy, and the local setup;
- **First steps:** up to 3 concrete steps toward a first small PR.

Every number and fact must come from something you fetched in this session. If you couldn't check something, say so. Fewer solid picks are better than ten weak ones.
