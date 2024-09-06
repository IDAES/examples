"""
Create/update TOC in a markdown document.

The TOC location is wherever the document has a **bold** line with just `TOC_TITLE`,
so by default this would be:

    **Table of Contents**

Then a bulleted list gives the contents.
"""

import argparse
import logging
import re
import shutil
import sys
from tempfile import NamedTemporaryFile
from typing import List, Tuple, Iterable

_log = logging.getLogger("markdown_toc")
h = logging.StreamHandler()
h.setFormatter(
    logging.Formatter("[%(levelname)s] %(asctime)s (%(module)s) - %(message)s")
)
_log.addHandler(h)

TOC_TITLE = "Table of Contents"
BOLD = "**"

heading_re = re.compile(r"\s*(#+)((\w|\s)+)")


def is_toc(line: str) -> bool:
    s = line.strip()
    return s == f"{BOLD}{TOC_TITLE}{BOLD}"


def is_pre(line: str) -> bool:
    s = line.strip()
    return s.startswith("```")


def get_heading(line: str) -> Tuple[int, str]:
    m = heading_re.match(line)
    if m is None:
        return 0, ""
    hashes, name = m.group(1), m.group(2).strip()
    return len(hashes), name


def get_headings(lines: Iterable, min_level: int = 1) -> List:
    headings = []
    special = False
    for line in lines:
        if is_pre(line):
            special = not special
        if special:
            continue
        level, heading = get_heading(line)
        if level >= min_level:
            headings.append((level, heading))
    return headings


def markdown_list(headings: List[Tuple[int, str]], min_level: int = 1) -> str:
    lines = (f"{' ' * (level - min_level)*2}* {heading}" for level, heading in headings)
    return "\n" + "\n".join(lines) + "\n"


def process(infile, outfile, min_level: int = 1) -> bool:
    inplace, outlines = outfile is None, []

    lines = list(infile.readlines())
    headings = get_headings(lines, min_level=min_level)
    added_toc, in_toc = False, 0
    for line in lines:
        if in_toc:
            if in_toc > 1 and not line.strip().startswith("*"):
                in_toc = 0  # out of TOC section
            else:
                in_toc += 1
                continue
        if inplace:
            outlines.append(line)
        else:
            outfile.write(line)
        if not added_toc and is_toc(line):
            if inplace:
                outlines.append(markdown_list(headings, min_level=min_level))
            else:
                outfile.write(markdown_list(headings))
            added_toc, in_toc = True, 1

    if inplace and added_toc:
        infile.close()
        new_infile = open(infile.name, mode="w", encoding="utf-8")
        for line in outlines:
            new_infile.write(line)

    return added_toc


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("infile", nargs="?", default=None, help="Input file (default=stdin)")
    p.add_argument(
        "--out", dest="outfile", default=None, help="Output file (default=stdout)"
    )
    p.add_argument("--inplace", "-i", help="Modify input file", action="store_true")
    p.add_argument(
        "--min-level", "-m", help="Minimum level to include", default=1, type=int
    )
    args = p.parse_args()

    _log.setLevel(logging.INFO)

    if args.infile is None:
        infile = sys.stdin
    else:
        infile = open(args.infile, "r", encoding="utf-8")

    if args.inplace:
        outfile = None
        if args.outfile is not None:
            _log.warning("--out argument ignored with --inplace argument")
    elif args.outfile is None:
        outfile = sys.stdout
    else:
        outfile = open(args.outfile, "w", encoding="utf-8")

    had_toc = process(infile, outfile, min_level=args.min_level)
    _log.info(f"Done: table of contents {'updated' if had_toc else 'not found'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
