"""
Common variables and methods for tests and scripts.
"""
# stdlib
from enum import Enum
import logging
from pathlib import Path
from typing import Dict

# third-party
import yaml

_log = logging.getLogger(__name__)

src_suffix = "_src"
src_suffix_len = 4


NB_ROOT = "notebooks"  # root folder name
NB_CELLS = "cells"  # key for list of cells in a Jupyter Notebook
NB_META = "metadata"  # notebook-level metadata key
NB_IDAES, NB_SKIP = "idaes", "skip"  # key and sub-key for notebook skipping


class Tags(Enum):
    EX = "exercise"
    SOL = "solution"
    TEST = "testing"
    AUTO = "auto"
    NOAUTO = "noauto"


class Ext(Enum):
    DOC = "doc"
    EX = "exercise"
    SOL = "solution"
    TEST = "test"
    USER = "usr"


def add_vb(p, dest="vb"):
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        dest=dest,
        default=0,
        help="Increase verbosity",
    )


def process_vb(log, vb):
    if vb >= 2:
        log.setLevel(logging.DEBUG)
    elif vb == 1:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARNING)


def add_vb_flags(logger, cmdline):
    vb_count = 0
    if logger.isEnabledFor(logging.DEBUG):
        vb_count = 2
    elif logger.isEnabledFor(logging.INFO):
        vb_count = 1
    if vb_count > 0:
        vbs = "v" * vb_count
        cmdline.append(f"-{vbs}")


def allow_repo_root(src_path, func) -> Path:
    """This allows commands to (also) work if src_path is the repo root (as opposed
    to the directory with the notebooks in it).
    """
    src_path = Path(src_path)
    if not (src_path / NB_ROOT).exists():
        mod = func.__module__.split(".")[0]
        if (src_path / mod / NB_ROOT).exists():
            src_path /= mod
    return src_path


def read_toc(src_path: Path) -> Dict:
    """Read and parse Jupyterbook table of contents.

    Args:
        src_path: Path to source directory containing TOC file

    Returns:
        Parsed TOC contents

    Raises:
        FileNotFoundError: If TOC file does not exist
    """
    toc_path = src_path / "_toc.yml"
    if not toc_path.exists():
        raise FileNotFoundError(f"Could not find path: {toc_path}")
    with toc_path.open() as toc_file:
        toc = yaml.safe_load(toc_file)
    return toc


def find_notebooks(nbpath: Path, toc: Dict, callback, **kwargs) -> int:
    """Find and preprocess all notebooks in a Jupyterbook TOC.

    Args:
        nbpath: Path to root of notebook files
        toc: Table of contents from Jupyterbook
        callback (Callable[[Path, ...]): Function called for each found notebook,
                with the path to that notebook as its first argument.
        **kwargs: Additional arguments passed through to the callback

    Returns:
        Number of notebooks processed
    """
    n = 0
    for part in toc["parts"]:
        for chapter in part["chapters"]:
            # list of {'file': name} dicts for each section, or just one for each chapter
            filemap_list = chapter.get("sections", [chapter])
            for filemap in filemap_list:
                filename = filemap["file"][:-4]  # strip "_doc" suffix
                filename += src_suffix
                path = nbpath / f"{filename}.ipynb"
                if path.exists():
                    _log.debug(f"Found notebook at: {path}")
                    callback(path, **kwargs)
                    n += 1
                else:
                    raise FileNotFoundError(f"Could not find notebook at: {path}")
    return n
