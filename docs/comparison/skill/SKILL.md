---
name: find-api-docs-to-contribute
description: Find open-source projects that serve a REST API, have real gaps in their API documentation, and are likely to merge a docs pull request from a newcomer. Use when someone asks for API documentation they could contribute to.
---

# Find API docs to contribute to

You're helping a technical writer find open-source projects where a documentation pull request would be welcome and useful. Every pick must meet all three conditions:

1. **It serves a REST API:** a running app or service that exposes HTTP endpoints to its users, such as a self-hosted app, a server or a platform. Rule out API clients, SDKs, wrappers, code generators, spec validators, frameworks or libraries for building APIs, CLIs and lists of links. Docker or compose files and words like "self-hosted", "server" or "dashboard" point to an app.
2. **Its API docs have a real gap** that you can show with numbers and links.
3. **It's likely to accept a pull request from an outsider.**

## Tools

- `ghapi PATH [curl options]` calls the GitHub API with the user's token, for example:
  - `ghapi /repos/OWNER/REPO`
  - `ghapi '/search/repositories?q=...'`
  - `ghapi /graphql -X POST -d @query.json`

  It also fetches `https://raw.githubusercontent.com/...` files. Never read or print the token.
- The search API allows 30 requests a minute.
- REST lists of pull requests and commits are large (about 19 KB per pull request). List them through GraphQL, asking only for the fields you need.
- Work in the current folder, and save notes as you go.

## Where to look (best first)

1. **awesome-selfhosted** ([awesome-selfhosted-data](https://github.com/awesome-selfhosted/awesome-selfhosted-data)): about 1,350 hand-picked self-hosted apps.
   - Each app is one YAML file under `software/`, with a `source_code_url`.
   - It's the best source by far: most entries are real apps, and many have an API.
   - The contents API stops listing a folder at 1,000 entries. Download the tarball instead (`ghapi /repos/awesome-selfhosted/awesome-selfhosted-data/tarball > a.tgz`) and read it with `tar`.
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

Put one keyword in each query; `(openapi OR swagger) in:title` returns tens of thousands of junk results.

## Likely to accept a PR (check this before measuring gaps)

- Not archived, not a fork, has a license, stars within the user's range, and pushed in the last 60 days.
- At least 2 human committers (not bots) in the last 90 days.
- At least 1 pull request from an outsider merged in the last 180 days.
  - An outsider's author association isn't OWNER, MEMBER or COLLABORATOR.
  - Ignore bots and dependency bumps (Dependabot, Renovate).
- Exception: when a maintainer labeled a docs issue "help wanted" or "good first issue", 1 committer and no outside merges are enough.

## Finding the gap (measure, don't guess)

- **An OpenAPI or Swagger spec in the repo** (`openapi.yaml`, `swagger.json` and so on). Use the git tree API with `?recursive=1` to find it.
  - Skip vendored copies, tests, examples, and specs with fewer than 3 operations.
  - Count the operations with:
    - no summary or description;
    - parameters without descriptions;
    - no examples;
    - no 2xx schema;
    - no 4xx or 5xx responses.
  - Also check for an `info.description` under 50 characters, security schemes without descriptions, and no servers.
  - Report counts, such as "21/38 operations have no description", with example operations.
- **A generated spec:** a "DO NOT EDIT" or "generated" header, or a CI job that regenerates the file. The fix belongs in the code annotations, so say so.
- **No spec:** look for endpoint documentation in the README and `docs/`. For each documented endpoint, check for a description, a request example, a response example, status and error codes, and auth. Report what's missing, with counts.
- **Docs elsewhere:** before calling docs missing, check:
  - the homepage;
  - docs links in the README, but only addresses that belong to the project (a framework's docs don't count);
  - the owner's sibling `*-docs` or `*website*` repo;
  - whether the app serves Swagger UI, ReDoc or `openapi.json` when it runs.

  If the docs live somewhere you can't read, say "check manually", not "no docs".
- An open issue from a maintainer about the API docs is the strongest gap evidence. Link it.

## Before recommending

- **Already claimed?** Look for open PRs that touch the docs or the spec, and for comments like "I'll take this" or "working on it" on the issue.
- **Requirements:** a CLA to sign, a DCO sign-off on commits, or an AI-contribution policy. Quote the sentence you found.
- **Local setup:** easy (Docker, compose or a devcontainer), documented, or unclear.

## Output

A ranked list, best first. For each pick:

- the `owner/repo` link, stars, main language and last push;
- **Serves an API because:** one line of evidence;
- **The gap:** the measured facts, each linked to the file (a permalink with a commit SHA) or the issue;
- **Likely to merge:** outside PRs merged in the last 180 days and committers in the last 90 days;
- **Before you start:** whether it's claimed, any CLA, DCO or AI policy, and the local setup;
- **First steps:** up to 3 concrete steps toward a first small PR.

Every number and fact must come from something you fetched in this session. If you couldn't check something, say so. Fewer solid picks are better than ten weak ones.
