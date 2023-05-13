"""
Common variables and methods for tests and scripts.
"""
# stdlib
from enum import Enum
import logging
from pathlib import Path
from typing import Dict, List, Any

# third-party
import yaml

_log = logging.getLogger(__name__)
_h = logging.StreamHandler()
_h.setFormatter(
    logging.Formatter("[%(levelname)s] %(asctime)s %(module)s - %(message)s")
)
_log.addHandler(_h)

src_suffix = "_src"
src_suffix_len = 4


NB_ROOT = "notebooks"  # root folder name
NB_CACHE = ".jupyter_cache"  # cache subdirectory
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


ExtAll = {Ext.DOC, Ext.EX, Ext.SOL, Ext.TEST, Ext.USER}


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


def find_notebook_root(src_path) -> Path:
    """This allows commands to (also) work if src_path is the repo root (as opposed
    to the directory with the notebooks in it).
    """
    level = logging.getLogger("")

    def is_notebook_dir(p):
        return (
            (p / NB_ROOT).exists()
            and (p / NB_ROOT).is_dir()
            and (p / NB_ROOT / "_toc.yml").exists()
            and (p / NB_ROOT / "_config.yml").exists()
        )

    result = None

    src_path = Path(src_path).absolute()

    _log.info(f"Find notebook root starting from: {src_path}")
    # Try input dir
    _log.debug(f"Find notebook root; try: {src_path}")
    if is_notebook_dir(src_path):
        result = src_path
    else:
        # Try (input dir / idaes_examples)
        mod_path = src_path / "idaes_examples"
        _log.debug(f"Find notebook root; try: {mod_path}")
        if is_notebook_dir(mod_path):
            result = mod_path
        else:
            # Try parents of input dir
            _log.debug(f"Find notebook root; try parents of {src_path}")
            while src_path.parent != src_path:
                src_path = src_path.parent
                _log.debug(f"Find notebook root; try: {src_path}")
                if is_notebook_dir(src_path):
                    result = src_path
                    break

    if result is None:
        raise FileNotFoundError(f"Directory '{NB_ROOT}' not found")

    _log.info(f"Find notebook root result: {result}")
    return result


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


def find_notebooks(nbpath: Path, toc: Dict, callback, **kwargs) -> Dict[Path, Any]:
    """Find and preprocess all notebooks in a Jupyterbook TOC.

    Args:
        nbpath: Path to root of notebook files
        toc: Table of contents from Jupyterbook
        callback (Callable[[Path, ...]): Function called for each found notebook,
                with the path to that notebook as its first argument.
        **kwargs: Additional arguments passed through to the callback

    Returns:
        Mapping of paths to return values from calls to processed notebooks
    """
    results = {}
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
                    results[path] = callback(path, **kwargs)
                else:
                    raise FileNotFoundError(f"Could not find notebook at: {path}")
    return results
