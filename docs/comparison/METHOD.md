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

## Round 2 (16 Oct): after fixing DocScout

Round 1 showed DocScout's blind spots, and they were fixed in 43965ee. Round 2 repeats Test 2, with these changes, which are fixed before anything runs:

- **The same new knowledge for both sides.** The author prefers projects whose docs are published as pages. DocScout got this as a ranking bonus, and the skill got the same preference as a paragraph near its top ([skill/SKILL.md](skill/SKILL.md)).
- **New projects only.** The agent is told to skip the 13 projects graded in round 1. DocScout's search (`43965ee`, a fresh data folder, clock set to the round 1 start) happens to include none of them.
- **Gemma reviews DocScout's candidates** on the laptop's available memory, as in round 1.
- **Grading, fact-check and costs** follow the round 1 rules: blind grading by the author, every gap claim checked against the cited commit by a separate agent, and the same cost measures.
- **Test 1 isn't repeated.** Neither the classifier nor the agent's definition of "serves an API" changed.

## Round 3 (17 Oct): both sides updated

Both sides changed after round 2, so Test 2 runs again with the versions that are submitted. Fixed before anything runs:

- **DocScout** at `1aaec67`, with the hosted version's model: Gemma 4 31B on Google's API, and Gemma 4 26B when the 31B is busy ([deploy/render.toml](../../deploy/render.toml)). One `docscout run` in a fresh data folder, checking at most 60 repos as before. Up to 30 reviews and 30 new picks, so every project Gemma accepts is reported. New since round 2:
  - gaps covering fewer than 5 operations or endpoints aren't reported;
  - Gemma decides whether someone is already working on a gap;
  - install commands aren't counted as endpoints;
  - each pick leads with its biggest gap.
- **The agent:** a Claude Code subagent (Claude Opus 5.5) given the public skill, [skills/find-api-docs-to-contribute/SKILL.md](../../skills/find-api-docs-to-contribute/SKILL.md), as a user of it would be:
  - a shell, and the GitHub API through `curl` with the user's token (this laptop has no GitHub CLI);
  - it may read a project's homepage, docs site and wiki, but may not use web search;
  - it can't see DocScout's code, data or labels;
  - the request: REST API docs, any language, 20–5,000 stars, up to 10 picks, at most 60 repos checked in depth.
- **New projects only.** Both sides skip the 27 projects graded in rounds 1 and 2, and the 6 picks from the hosted version's first runs that the author saw on 17 Oct (shurco/mycart, smaramwbc/statewave, Emmy123222/Stellar-MarketPay-, vsys-host/shkeeper.io, ergochat/ergo, Bike4Mind/bike4mind), which would break the blinding. DocScout gets them as ignored in its fresh database; the agent gets the list.
- **Grading, fact-check and objective checks** as in rounds 1 and 2: blind grading by the author, every gap claim checked against the cited commit by a separate agent, and the same health check. "Not already claimed" is judged with the claim rules in the public skill, which are the rules Gemma follows.
- **Costs:** time, the agent's tokens, and DocScout's GitHub API calls and Gemma requests. The agent's GitHub calls aren't logged this round: it calls `curl` directly, as a user of the skill would.
- **Test 1 isn't repeated.**

**Added after DocScout's run, before any grading (17 Oct, 10:45 UTC).** DocScout's fixed run checked its 60 repos and reported nothing: 13 passed the health checks, and 11 of them keep their docs on a website DocScout can't read yet (M4), with no help request. That result stands as round 3's. One extra run, reported separately: the same search continued to 200 repos, the hosted version's daily setting, in the same data folder. Its picks join the blind grading, so the agent's picks aren't the only ones on the sheet.
