# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which reader reads which watched file. A file type the watch learns later is one more entry in
`READERS`; a path with no entry is skipped with a warning, never guessed at."""
import logging
from collections.abc import Callable, Generator, Mapping

from .kmsg import kmsg_messages

_log = logging.getLogger(__name__)

MessageSource = Callable[[str, int], Generator[str, None, None]]
"""A reader: given the file's path and the wake pipe's read end, it yields each new line until the
wake pipe is written to."""

READERS: dict[str, MessageSource] = {"/dev/kmsg": kmsg_messages}


def supported_sources(
    files: list[str], readers: Mapping[str, MessageSource],
) -> list[tuple[str, MessageSource]]:
    """Each watched file that has a reader, with its reader, each path once."""
    unique_files = list(dict.fromkeys(files))
    for path in unique_files:
        if path not in readers:
            _log.warning("active watch: %s is not supported yet, skipped", path)
    return [(path, readers[path]) for path in unique_files if path in readers]
