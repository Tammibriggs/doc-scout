"""The hosted daily job (a Render cron job): ``python -m docscout.hosted.job``.

1. Run ``docscout run`` with the hosted settings (``DOCSCOUT_CONFIG``, by default
   ``deploy/render.toml``): Gemma 4 on Google's API, no desktop notifications, and DocScout's
   memory in MongoDB Atlas collections (``[storage] backend = "atlas"``), since a cron job
   starts on an empty machine each day.
2. Publish the picks from the last 7 days to Atlas for the website, even after a failed or
   cut-off run, since DocScout saves its progress as it goes.

Until 18 Oct the job copied DocScout's memory, a SQLite file, in and out of Atlas GridFS around
each run. The first run with an empty set of collections moves that file into them.

Secrets come from the environment (Render's settings) or DocScout's secrets.env: ``MONGODB_URI``,
``GITHUB_TOKEN`` and ``DOCSCOUT_LLM_API_KEY``.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path("deploy") / "render.toml"  # relative to the repo checkout, where Render runs the job
log = logging.getLogger("docscout.hosted.job")


def move_sqlite_memory(atlas: Any, store: Any) -> dict[str, int] | None:
    """Move the memory kept in GridFS until 18 Oct into the collections, once: only while the
    collections are empty. The file stays in GridFS as a backup. Returns the counts moved."""
    if not store.is_empty():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "docscout.db"
        if not atlas.load_state(path):
            return None
        return store.import_sqlite(path)


def main(argv: list[str] | None = None, atlas: Any = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # DocScout keeps its lock, caches and reports under XDG_DATA_HOME; on Render that's a scratch folder.
    os.environ.setdefault("XDG_DATA_HOME", "/tmp/docscout-data")

    from docscout import cli
    from docscout.find import health
    from docscout.hosted.atlas_store import AtlasStore
    from docscout.hosted.picks import weekly_picks
    from docscout.settings.config import load_config

    config = os.environ.get("DOCSCOUT_CONFIG", str(DEFAULT_CONFIG))
    cfg = load_config(Path(config))
    if cfg["storage"]["backend"] != "atlas":
        log.error('%s must set [storage] backend = "atlas": a cron job starts on an empty machine, so a SQLite file would be lost', config)
        return 2
    if atlas is None:
        from docscout.hosted import required_secret
        from docscout.hosted.atlas import Atlas

        atlas = Atlas(required_secret("MONGODB_URI"))
    store = AtlasStore(atlas.db)
    moved = move_sqlite_memory(atlas, store)
    if moved:
        log.info("moved DocScout's memory from GridFS into Atlas collections: %s", moved)
    code = 1
    try:
        code = cli.main(["--config", config, "run", *(argv or [])])
    finally:
        picks = weekly_picks(store, health.utcnow(), int(cfg["report"]["min_effort_units"]))
        atlas.publish(picks, health.utcnow())
        log.info("published %d picks", len(picks))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
