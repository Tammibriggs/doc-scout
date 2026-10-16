"""The hosted daily job (a Render cron job): ``python -m docscout.hosted.job``.

1. Copy DocScout's database from Atlas into this short-lived machine.
2. Run ``docscout run`` with the hosted settings (``DOCSCOUT_CONFIG``, by default
   ``deploy/render.toml``: Gemma 4 on Google's API, no desktop notifications).
3. Publish this week's picks to Atlas for the website.
4. Copy the database back, even after a failed or cut-off run, since DocScout saves its
   progress as it goes.

Secrets come from the environment: ``MONGODB_URI``, ``GITHUB_TOKEN`` and ``DOCSCOUT_LLM_API_KEY``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

DEFAULT_CONFIG = Path("deploy") / "render.toml"  # relative to the repo checkout, where Render runs the job
log = logging.getLogger("docscout.hosted.job")


def main(argv: list[str] | None = None, atlas: object | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # DocScout keeps its files under XDG_DATA_HOME; on Render that's a scratch folder.
    os.environ.setdefault("XDG_DATA_HOME", "/tmp/docscout-data")

    from docscout import cli
    from docscout.config import data_dir
    from docscout.db import Store
    from docscout.health import utcnow
    from docscout.hosted.picks import weekly_picks

    if atlas is None:
        from docscout.hosted.atlas import Atlas

        atlas = Atlas(os.environ["MONGODB_URI"])
    config = os.environ.get("DOCSCOUT_CONFIG", str(DEFAULT_CONFIG))
    db_path = data_dir() / "docscout.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("memory from Atlas: %s", "loaded" if atlas.load_state(db_path) else "none yet (first run)")
    code = 1
    try:
        code = cli.main(["--config", config, "run", *(argv or [])])
    finally:
        if db_path.exists():
            store = Store(db_path)
            try:
                picks = weekly_picks(store, utcnow())
            finally:
                store.close()
            atlas.publish(picks, utcnow())
            atlas.save_state(db_path)
            log.info("published %d picks; memory saved to Atlas", len(picks))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
