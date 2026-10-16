# DocScout vs. an AI agent with a skill

The question: could someone get the same result by giving an AI agent a good skill, without DocScout? This file fixes the method before anything runs (14 Oct 2026). The results go in [RESULTS.md](RESULTS.md).

## The two sides

- **DocScout** (branch `m2-llm`, with `gemma4:e2b` running locally): one `docscout run` in a fresh data folder, so it can't reuse earlier finds.
- **An agent with a skill:**
  - The agent is a Claude Code agent (Claude Opus 5.5), given only the skill in [skill/SKILL.md](skill/SKILL.md), a shell, and `ghapi`, a `curl` wrapper that adds the GitHub token and logs every call. It may also read a project's own homepage or docs site, which DocScout can't do until M4. It may not use web search.
  - It can't see DocScout's code, data or labels.
  - The skill includes what building DocScout taught us: the best sources, the search pitfalls, the health thresholds and how to measure a gap. That makes it the strongest version of "an agent with a skill", not a naive one.

## Test 1: the 58 labeled repos

- The agent gets the 58 repo names from `tests/fixtures/labeled_repos.csv`, without the labels. For each one, it decides whether the repo serves an API, using the skill's definition.
- Score: precision and recall for "serves an API" against the hand labels.
- Already measured for DocScout:

  | Setup | Precision | Recall |
  |---|---|---|
  | Code only | 76% | 90% |
  | Code plus Gemma | 81% | 81% |
  | Gemma alone, on the 50 repos with code confidence ≥ 0.4 | 80% | 80% |

## Test 2: one search

- Same profile for both: REST APIs, any language, 20–5,000 stars.
- Same limit: at most 60 repos checked in depth (DocScout's daily budget).
- The agent is asked for up to 10 picks. DocScout reports what its run finds, which can be fewer.

Each pick is graded three ways:

1. **Blind, by the project's author:** the picks from both sides are mixed and shown without their source. For each, the author answers:
   - Does it serve a REST API? (yes / no)
   - Would I act on it? (yes / maybe / no)

   The second question is also the M1 exit check (act on at least 3 of the top 10).
2. **Every factual claim about the gap** (counts, missing parts, files, issues) is checked against the repo at the commit cited, or as of today. Each is right, wrong or can't be checked. A pick whose main gap claim is wrong counts as a wrong pick.
3. **The same objective checks for both:** healthy (an outside PR merged in the last 180 days), and not already claimed (no open PR touching the docs or spec).

## Cost

- Wall-clock time.
- GitHub API calls: DocScout's run record, and the agent's `ghapi` log.
- The agent's tokens.
- DocScout's peak memory with Gemma loaded.

## Not tested, noted only

- **Day 2:** DocScout remembers what it showed, ignored or finished. A skill needs its own notes file for that.
- **Running unattended:** schedule, offline, cut-off runs and alerts.
- **Prompt injection:** the agent reads untrusted READMEs while holding a shell and a token. DocScout's model has no tools, and code caps how far its opinion can move a score.
