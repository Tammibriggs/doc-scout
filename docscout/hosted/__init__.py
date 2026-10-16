"""The hosted version: DocScout for writers who'd rather not run it themselves.

- A Render cron job runs DocScout once a day (:mod:`docscout.hosted.job`), with Gemma 4 served
  by Google's API, so nothing needs a laptop or 6 GB of free memory.
- MongoDB Atlas keeps DocScout's memory between runs (the SQLite file the job can't keep on
  Render), this week's picks, and the subscriptions (:mod:`docscout.hosted.atlas`).
- A small website (:mod:`docscout.hosted.web`) shows the week's top picks for free and the
  rest to subscribers, who pay through Stripe Checkout (:mod:`docscout.hosted.billing`).

Install with ``pip install -e ".[hosted]"``. The command-line tool doesn't need any of it.
"""
