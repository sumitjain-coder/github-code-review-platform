"""
DIFF POSITION MAPPING
-----------------------
GitHub's inline review comments don't use normal file line numbers.
They use "position": the line's offset within that file's diff
patch, counted in a specific way. This file's only job is
converting "line 42 in auth.py" into "position 7 in the diff" so
GitHub knows exactly where to attach a comment.

How the counting works, in plain terms:
  - We walk through the patch text line by line.
  - Every line we look at (including the "@@" hunk header itself)
    increases the position counter by 1.
  - Only "added" lines (starting with "+") and "context" lines
    (unchanged lines shown for reference, starting with a space)
    correspond to a real line number in the NEW version of the file.
  - "Removed" lines (starting with "-") still increase position,
    but don't correspond to any line in the new file, so we skip
    mapping them.
"""

import re

HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def build_line_to_position_map(patch_text):
    """
    Given one file's patch text, returns a dict like:
        { 14: 7, 15: 8, 16: 9, ... }
    mapping "line number in the new file" -> "position in the diff".

    If a line number the AI mentioned isn't in this map, it means
    that line wasn't actually touched by this diff (or the AI
    guessed slightly wrong) — callers should handle that gracefully.
    """
    line_to_position = {}
    position = 0
    current_new_line = None

    for line in patch_text.split("\n"):
        position += 1

        hunk_match = HUNK_HEADER_PATTERN.match(line)
        if hunk_match:
            # The number after "+" tells us what line number the NEW
            # file starts at for this hunk. We subtract 1 because
            # we'll increment it before using it, on the next line.
            current_new_line = int(hunk_match.group(1)) - 1
            continue

        if current_new_line is None:
            # We haven't hit a hunk header yet (e.g. we're still in
            # the "diff --git ..." style preamble, if present).
            continue

        if line.startswith("-"):
            # A removed line: takes up a position, but has no
            # corresponding line number in the new file.
            continue

        # Either an added line ("+") or an unchanged context line
        # (starts with a space) — both exist in the new file.
        current_new_line += 1
        line_to_position[current_new_line] = position

    return line_to_position
