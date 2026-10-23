"""Watching a vault while orbit runs, so that notes edited in Obsidian or by any other program are in the index
within a second."""

import logging
import sqlite3

import watchfiles

from . import console
from .errors import OrbitError
from .vault import is_hidden

log = logging.getLogger(__name__)
DEBOUNCE_MS = 50  # changes that come together are taken together
STEP_MS = 50


async def watch(crm, stop):
    """Refresh `crm`'s index with every change to its vault, until the anyio Event `stop` is set. Hidden folders are
    left out: Obsidian rewrites its .obsidian whenever a note is opened."""
    logging.getLogger("watchfiles").setLevel(logging.WARNING)  # its "1 change detected" for every change says nothing

    def visible(change, path):
        rel = crm.vault.rel(path)
        return rel is not None and not is_hidden(rel)

    async for changes in watchfiles.awatch(
        crm.vault.root, stop_event=stop, debounce=DEBOUNCE_MS, step=STEP_MS, watch_filter=visible
    ):
        paths = {crm.vault.rel(path) for _, path in changes} - {None}
        try:
            crm.refresh(paths)
        except (OSError, sqlite3.Error, OrbitError) as e:  # a file another program holds, say; the next change mends it
            console.say(f"warning: couldn't index changes to {', '.join(sorted(paths))}: {e}")
        except Exception as e:  # a bug, which mustn't stop the server the watcher runs beside
            log.exception("indexing changes failed")
            console.say(f"warning: couldn't index changes to {', '.join(sorted(paths))}: {type(e).__name__}: {e}")
