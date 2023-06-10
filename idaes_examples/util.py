"""
Common variables and methods for tests and scripts.
"""
# stdlib
import datetime
from enum import Enum
import logging
from pathlib import Path
import re
import time
from typing import Dict, List, Any, Union, Tuple

# third-party
import yaml

_log = logging.getLogger(__name__)
_h = logging.StreamHandler()
_h.setFormatter(
    logging.Formatter("[%(levelname)s] %(asctime)s %(module)s - %(message)s")
)

_log.addHandler(_h)


NB_ROOT = "notebooks"  # root folder name
NB_CACHE = ".jupyter_cache"  # cache subdirectory
NB_CELLS = "cells"  # key for list of cells in a Jupyter Notebook
NB_META = "metadata"  # notebook-level metadata key
NB_IDAES, NB_SKIP = "idaes", "skip"  # key and sub-key for notebook skipping
# File extension that marks a Jupyter notebook
JUPYTER_EXT = ".ipynb"


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

EXT_RE = re.compile(r"(.*_)(\w+)\.ipynb$")


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


def find_notebook_root(src_path: Union[str, Path, None] = None) -> Path:
    """This allows commands to (also) work if src_path is the repo root (as opposed
    to the directory with the notebooks in it).
    """

    def is_notebook_dir(p):
        return (
            (p / NB_ROOT).exists()
            and (p / NB_ROOT).is_dir()
            and (p / NB_ROOT / "_toc.yml").exists()
            and (p / NB_ROOT / "_config.yml").exists()
        )

    result = None

    if src_path is None:
        src_path = Path.cwd().absolute()
    else:
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
                if is_notebook_dir(src_path / "idaes_examples"):
                    result = src_path / "idaes_examples"
                    break

    if result is None:
        raise FileNotFoundError(f"Directory '{NB_ROOT}' not found")

    _log.info(f"Find notebook root result: {result}")
    return result


def read_toc(src_path: Union[Path, str]) -> Dict:
    """Read and parse Jupyterbook table of contents.

    Args:
        src_path: Path to source directory containing TOC file

    Returns:
        Parsed TOC contents

    Raises:
        FileNotFoundError: If TOC file does not exist
    """
    toc_path = Path(src_path) / "_toc.yml"
    if not toc_path.exists():
        raise FileNotFoundError(f"Could not find path: {toc_path}")
    with toc_path.open() as toc_file:
        toc = yaml.safe_load(toc_file)
    return toc


def find_notebooks(
    nbpath: Union[Path, str], toc: Dict, callback, **kwargs
) -> Dict[Path, Any]:
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
    nbpath = Path(nbpath)
    results = {}
    for part in toc["parts"]:
        for chapter in part["chapters"]:
            # list of {'file': name} dicts for each section,
            # or just one for each chapter
            filemap_list = chapter.get("sections", [chapter])
            for filemap in filemap_list:
                filename = filemap["file"][:-4]  # strip "_doc" suffix
                path = nbpath / f"{filename}.ipynb"
                if path.exists():
                    _log.debug(f"Found notebook at: {path}")
                    results[path] = callback(path, **kwargs)
                else:
                    raise FileNotFoundError(f"Could not find notebook at: {path}")
    return results


class NotebookCollection:
    def __init__(self, root: Path = None):
        """Constructor.

        Raises:
            FileNotFoundError: If notebooks can't be found
        """
        self._root = find_notebook_root(root)
        self._nb = self._root / "notebooks"
        self._missing, self._stale = None, None

    def get_notebooks(self) -> List[Path]:
        """Get a list of notebooks."""
        toc = read_toc(self._nb)
        notebooks = []

        def add_notebook(p, **kwargs):
            notebooks.append(p)

        find_notebooks(self._nb, toc, callback=add_notebook)
        return notebooks

    @property
    def missing(self) -> List[Path]:
        """Derived notebooks that should be there, but are not.
        Currently, this is notebooks of form `{name}_doc.ipynb` when there
        is a notebook like `{name}.ipynb`.

        Returns:
            List of paths for the missing notebooks
        """
        self._find_missing_and_stale()
        return self._missing

    @property
    def stale(self) -> Dict[Path, Tuple[Path, datetime.timedelta]]:
        """Derived notebooks that are older than their source.
        Notebooks of the form `{name}_{ext}.ipynb` that are newer than
        their source `{name}_source.ipynb`.

        Returns:
            Map of source paths -> tuple of (stale path, time older than source).
        """
        self._find_missing_and_stale()
        return self._stale

    def _find_missing_and_stale(self) -> None:
        if self._missing is not None:  # result cached
            return
        stale, missing = {}, []
        for p in self.get_notebooks():
            assert p.exists()
            p_info = p.stat()
            for ext in ExtAll:
                q = change_notebook_ext(p, ext.value)
                if ext is Ext.DOC:
                    if not q.exists():
                        missing.append(q)
                if q.exists():
                    q_info = q.stat()
                    delta = q_info.st_mtime - p_info.st_mtime
                    if delta < 0:
                        td = datetime.timedelta(seconds=-delta)
                        if p not in stale:
                            stale[p] = []
                        stale[p].append((q, td))
        self._missing, self._stale = missing, stale


def change_notebook_ext(p: Path, e: str) -> Path:
    """New path with extension 'src', etc. changed to input extension."""
    suffix = path_suffix(p, must_exist=False)
    if suffix is None:
        raise ValueError(f"path '{p}' is not recognized as a Jupyter notebook")
    if suffix == "":
        name = p.stem
    else:
        name = p.stem[: -(len(suffix) + 1)]
    return p.parent / f"{name}_{e}{JUPYTER_EXT}"


def path_suffix(
    p: Path, extra: List[str] = None, must_exist: bool = True
) -> Union[str, None]:
    """Get suffix for a path to a notebook.

    Args:
        p: Input path, should be a file
        extra: If given, extra suffixes to consider 'known'
        must_exist: If True the file must exist; otherwise don't check this

    Returns:
        * None - if not a file or filename doesn't end in .ipynb
        * {sfx} - if filename ends in `_{sfx}.ipynb` where `{sfx}` is known
        * "" - otherwise (i.e. a notebook that doesn't have a known suffix)
    """
    if not p.name.endswith(JUPYTER_EXT):
        return None
    if must_exist and not p.is_file():
        return None
    u = p.stem.rfind("_")
    if u == -1:
        return ""
    suffix = p.stem[u + 1 :]
    known_values = [e.value for e in ExtAll]
    if extra:
        known_values.extend(extra)
    for known in known_values:
        if known == suffix:
            return suffix
    return ""


def processing_report(
    action: str, t0: float, results: Dict, log: logging.Logger
) -> str:
    dur = time.time() - t0
    n = len(results)
    n_processed = sum(results.values())
    n_skipped = n - n_processed
    _log.info(
        f"{action.title()} {n} notebooks (did {n_processed} / "
        f"skipped {n_skipped}) in {dur:.1f} seconds"
    )
    return f"{action} {n_processed}, skipped {n_skipped}"
