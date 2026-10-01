#!/usr/bin/env python3
"""
Atomic CSV write helpers for pipeline source-of-truth files.

target-companies.csv and applications.csv are the pipeline's source of
truth. Writing them in place means a crash mid-write leaves a truncated
or half-written file. Every writer must go through this module instead.

How it works: write the full contents to a temp file in the same
directory as the target, flush and fsync it, then os.replace() it onto
the target. os.replace() is atomic on POSIX (same filesystem), so a
reader sees either the complete old file or the complete new file,
never a partial one. If anything fails before the replace, the target
is untouched and the temp file is removed.

No locking, no third-party dependencies. Concurrent writers are out of
scope here (last replace wins).
"""

from __future__ import annotations

import csv
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, TextIO


@contextmanager
def atomic_open(path: Path, encoding: str = 'utf-8', newline: str = '') -> Iterator[TextIO]:
    """Context manager yielding a writable text handle backed by a temp file.

    On clean exit the temp file is fsynced and atomically renamed onto
    ``path``. On any exception the temp file is deleted and ``path`` is
    left untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + '.', suffix='.tmp'
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline=newline) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def write_csv_atomic(
    path: Path,
    rows: Iterable[Dict],
    header: List[str],
    extrasaction: str = 'ignore',
) -> None:
    """Atomically write dict rows as CSV with the given header."""
    with atomic_open(path) as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction=extrasaction)
        w.writeheader()
        w.writerows(rows)


def write_csv_rows_atomic(path: Path, rows: Iterable[Sequence]) -> None:
    """Atomically write raw (list/tuple) rows as CSV. First row is the header."""
    with atomic_open(path) as f:
        w = csv.writer(f)
        w.writerows(rows)
