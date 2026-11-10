# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A diff's hunks with their context evened out, so every patch program places them the same way.

`diff` gives a hunk fewer context lines on one side only where the file began or ended there. GNU
patch told `-F0` reads that as "this hunk sits at the start (or end) of the file", BusyBox patch
reads it as "at the end", and Apple's patch reads it as neither. So a firmware update that added one
line at the end of a file broke a diff that still fitted it, on the printer and in CI, while the
same install went through on a Mac. Trimming the longer side down to the shorter one leaves every
kept line exact and nothing for any of them to anchor on. A hunk that touches the very first or
last line keeps its context as it is.
"""

import re
from itertools import accumulate, takewhile

HUNK_START = re.compile(r"(?m)^(?=@@ -)")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@([^\r\n]*)")
# patch ends a line only at a newline; str.splitlines also breaks on form feeds and the like.
HUNK_LINE = re.compile(r"[^\n]*\n|[^\n]+")
NO_NEWLINE_MARKER = "\\"
CONTEXT_MARKS = (" ", "\n", "\r")
LINE_WEIGHT = {"-": (1, 0), "+": (0, 1), NO_NEWLINE_MARKER: (0, 0)}
CONTEXT_WEIGHT = (1, 1)


def context_evened(diff_text: str) -> str:
    """The same diff, each hunk trimmed to as many context lines before its change as after it."""
    preamble, *hunks = HUNK_START.split(diff_text)
    return preamble + "".join(_hunk_evened(hunk) for hunk in hunks)


def _hunk_evened(hunk_text: str) -> str:
    hunk_lines: list[str] = HUNK_LINE.findall(hunk_text)
    header_line, *lines_after_header = hunk_lines
    header = HUNK_HEADER.match(header_line)
    if header is None:
        return hunk_text
    old_start, old_count, new_start, new_count = _header_numbers(header)
    body_length = _body_length(lines_after_header, old_count, new_count)
    if body_length is None:
        return hunk_text
    body, tail = lines_after_header[:body_length], lines_after_header[body_length:]
    leading, trailing = _context_run(body), _context_run(body[::-1])
    kept = min(leading, trailing)
    if kept == 0 or leading == trailing:
        return hunk_text
    dropped_front, dropped_back = leading - kept, trailing - kept
    dropped = dropped_front + dropped_back
    line_ending = header_line[len(header_line.rstrip("\r\n")):]
    new_header = (f"@@ -{old_start + dropped_front},{old_count - dropped} "
                  f"+{new_start + dropped_front},{new_count - dropped} @@{header.group(5)}")
    kept_lines = _trimmed_body(body, dropped_front, dropped_back)
    return new_header + line_ending + "".join(kept_lines + tail)


def _header_numbers(header: re.Match[str]) -> tuple[int, int, int, int]:
    """Where the hunk starts in the old and new file and how many lines it spans in each. A span
    the header leaves out is one line."""
    old_start, old_count, new_start, new_count = header.group(1, 2, 3, 4)
    return int(old_start), int(old_count or 1), int(new_start), int(new_count or 1)


def _body_length(lines_after_header: list[str], old_count: int, new_count: int) -> int | None:
    """How many lines belong to the hunk: until both its spans are used up, plus a no-newline note
    on its last line. None when the lines run out first, which is not a hunk to touch."""
    used = accumulate((_line_weight(line) for line in lines_after_header), _add_weights)
    complete = next((position + 1 for position, totals in enumerate(used)
                     if totals == (old_count, new_count)), None)
    if complete is None:
        return None
    notes = takewhile(_is_no_newline_note, lines_after_header[complete:])
    return complete + sum(1 for _ in notes)


def _line_weight(hunk_line: str) -> tuple[int, int]:
    """How many old-file and new-file lines this hunk line stands for."""
    return LINE_WEIGHT.get(hunk_line[:1], CONTEXT_WEIGHT)


def _add_weights(totals: tuple[int, int], weight: tuple[int, int]) -> tuple[int, int]:
    return totals[0] + weight[0], totals[1] + weight[1]


def _is_no_newline_note(hunk_line: str) -> bool:
    return hunk_line.startswith(NO_NEWLINE_MARKER)


def _is_context(hunk_line: str) -> bool:
    return hunk_line[:1] in CONTEXT_MARKS


def _context_run(body: list[str]) -> int:
    """Context lines before the first change, notes about a missing newline not counted."""
    file_lines = [hunk_line for hunk_line in body if not _is_no_newline_note(hunk_line)]
    return next((position for position, hunk_line in enumerate(file_lines)
                 if not _is_context(hunk_line)), len(file_lines))


def _trimmed_body(body: list[str], dropped_front: int, dropped_back: int) -> list[str]:
    """The hunk's lines without the context dropped at each end. A no-newline note goes with the
    line it describes."""
    positions = [position for position, hunk_line in enumerate(body)
                 if not _is_no_newline_note(hunk_line)]
    first_kept = positions[dropped_front]
    end = positions[len(positions) - dropped_back] if dropped_back else len(body)
    return body[first_kept:end]
