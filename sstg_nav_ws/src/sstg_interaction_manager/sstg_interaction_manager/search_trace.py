"""Append SEARCH-TRACE diagnostic lines to a shared log file.

The file is ~/sstg-data/logs/search_trace.log — a single append-only log that
aggregates events from both ROS nodes and the Vite dev server. We keep stdout
emission too (via the passed ROS logger) so nothing is lost if a reader only
looks at the terminal.

Line-level appends of <4KB are atomic on Linux, so concurrent writers from
multiple processes stay ordered without explicit coordination.
"""

import datetime
import os
import threading

_LOG_PATH = os.path.expanduser('~/sstg-data/logs/search_trace.log')
_LOCK = threading.Lock()

try:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
except Exception:
    pass


def search_trace(source: str, msg: str, logger=None) -> None:
    ts = datetime.datetime.now().isoformat(timespec='milliseconds')
    line = f'{ts} [pid={os.getpid()}][{source}] {msg}\n'
    try:
        with _LOCK:
            with open(_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(line)
    except Exception:
        pass
    if logger is not None:
        try:
            logger.info(msg)
        except Exception:
            pass
