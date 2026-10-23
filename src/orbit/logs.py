"""Each run of `orbit serve` keeps what it says in a file of its own, each line with its time:
ORBIT_HOME/logs/serve-2026-10-23_210509.log. Every log is kept."""

import logging

from . import settings

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_handler = None  # the log file of this run, while there is one
_level = None  # the root logger's level before


def start(name, now):
    """Log this run, whose kind `name` says, to a new file: what orbit says and every logger's records. Its path."""
    global _handler, _level
    folder = settings.current().home / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{name}-{now:%Y-%m-%d_%H%M%S}"
    path = next(p for n in range(1, 1000) if not (p := folder / (stem + (f"-{n}" if n > 1 else "") + ".log")).exists())
    _handler = logging.FileHandler(path, encoding="utf-8")
    _handler.setFormatter(logging.Formatter(FORMAT))
    root = logging.getLogger()
    root.addHandler(_handler)
    _level = root.level
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    return path


def attach(*names):
    """Log these loggers too, which don't pass their records on (uvicorn's)."""
    for name in names:
        if _handler and _handler not in logging.getLogger(name).handlers:
            logging.getLogger(name).addHandler(_handler)


def stop():
    """Close this run's log."""
    global _handler
    if _handler is None:
        return
    for logger in [logging.getLogger(), *map(logging.getLogger, list(logging.root.manager.loggerDict))]:
        if _handler in logger.handlers:
            logger.removeHandler(_handler)
    logging.getLogger().setLevel(_level)
    _handler.close()
    _handler = None
