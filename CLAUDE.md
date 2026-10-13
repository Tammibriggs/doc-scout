# DocScout

## Keep the plan up to date

[docs/PLAN.md](docs/PLAN.md) is the project plan and the record of decisions. Whenever something important changes, update it in the same commit as the change. Important means:

- a stage's status, scope or dates (the timeline table in section 1);
- a decision, a default or a threshold (a cutoff, weight, budget or source);
- a command, a setting or the behavior a user sees;
- something learned from real data or a live run that changes the approach;
- a risk that was found or resolved;
- the code layout (the ✅ markers) and the test count.

Don't update it for refactors, small fixes or wording that doesn't change behavior. If the plan and the code disagree, point it out instead of quietly picking one.

## Working in this repo

- Tests: `.venv/bin/pytest -q`. They must pass before every commit.
- Each stage has its own branch (`m1-report`, `m3-daily`, …), merged into `main` once its exit check passes.
- Never commit secrets, local samples or spreadsheet lock files.
