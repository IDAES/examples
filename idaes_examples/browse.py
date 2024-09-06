"""
Graphical examples browser
"""

# stdlib
from importlib import resources

import json
import logging
from logging.handlers import RotatingFileHandler
from multiprocessing import Process
from operator import attrgetter, itemgetter
from pathlib import Path
import re
from subprocess import Popen, DEVNULL, PIPE, TimeoutExpired
import time
from typing import Tuple, List, Dict, Iterable

try:
    from ctypes import windll
except:
    windll = None

# package
import idaes_examples
from idaes_examples.util import (
    find_notebooks,
    read_toc,
    NB_CELLS,
    Ext,
)

# -------------
#   Logging
# -------------

use_file = False
log_dir = Path.home() / ".idaes" / "logs"
_log = logging.getLogger("idaes_examples")
_log_stream = logging.StreamHandler()
_log.addHandler(_log_stream)


def setup_logging(lvl, console=False):
    """Log to a file, unless none can be opened."""
    global use_file, log_dir

    _log.setLevel(lvl)

    handler = _log_stream  # use stderr by default and as a fallback
    if not console:
        if log_dir.exists():
            use_file = True
        else:
            try:
                log_dir.mkdir(exist_ok=True, parents=True)
                use_file = True
            except OSError:
                pass
        if use_file:
            _log.debug(f"Redirecting logs to: {log_dir}/nb_browser.log")
            _log.removeHandler(handler)
            handler = RotatingFileHandler(
                log_dir / "nb_browser.log", maxBytes=64 * 1024, backupCount=5
            )

    handler.setFormatter(
        logging.Formatter(
            "[%(levelname)s] %(asctime)s %(name)s::%(module)s - %(message)s"
        )
    )
    _log.addHandler(handler)


def set_log_level(level):
    _log.setLevel(level)


# -------------


def find_notebook_dir() -> Path:
    """Find notebook source root."""
    root_path = None
    stack = [resources.files(idaes_examples)]
    while stack:
        d = stack.pop()
        if d.is_file():
            pass
        else:
            p = Path(d)
            if p.stem == "notebooks":
                _log.debug(f"find_noteboo_dir: root_path={p}")
                root_path = p
                break
            for item in d.iterdir():
                stack.append(item)
    return root_path


class Notebooks:
    """Container for all known Jupyter notebooks."""

    DEFAULT_SORT_KEYS = ("section", "name", "type")

    def __init__(self, sort_keys=DEFAULT_SORT_KEYS, srcdir=None, user_dir=False):
        self._nb = {}
        self._title_keys = []
        if user_dir:
            _log.debug(f"Loading notebooks from provided directory: {srcdir}")
            self._root = Path(srcdir)
            if not self._root.is_dir():
                raise ValueError(f"Invalid directory: {self._root}")
        else:
            _log.debug("Find notebook directory automatically")
            self._root = find_notebook_dir()
        _log.debug(f"Using notebook directory: {self._root}")
        self._root_key = "root"
        self._section_key_prefix = "s_"
        self._toc = read_toc(self._root)
        find_notebooks(self._root, self._toc, self._add_notebook)
        self._sorted_values = sorted(
            list(self._nb.values()), key=attrgetter(*sort_keys)
        )

    def _add_notebook(self, path: Path, **kwargs):
        name = path.stem
        section = path.relative_to(self._root).parts[:-1]
        for ext in Ext.USER.value, Ext.EX.value, Ext.SOL.value:
            tpath = path.parent / f"{name}_{ext}.ipynb"
            if tpath.exists():
                key = (section, name, ext)
                _log.debug(f"Add notebook. key='{key}'")
                self._nb[key] = Notebook(name, section, tpath, nbtype=ext)

    def __len__(self):
        return len(self._nb)

    @property
    def notebooks(self) -> Dict:
        """Underlying dict mapping a tuple of (section, name, type) to
        a Notebook object.
        """
        return self._nb

    def titles(self) -> List[str]:
        """Get list of all titles for notebooks."""
        return [nb.title for nb in self._nb.values()]

    def __getitem__(self, key):
        return self._nb[key]

    def keys(self) -> Iterable:
        return self._nb.keys()

    def as_table(self):
        tutorials = set()
        for nb in self._sorted_values:
            if nb.type == Ext.EX.value:
                tutorials.add(nb.section_parts)

        data = []
        metadata = []
        for nb in self._sorted_values:
            if nb.type != Ext.USER.value:
                continue
            parts = nb.section_parts
            is_tut = parts in tutorials
            nbtype = "Tutorial" if is_tut else "Example"
            nbloc = Notebook.SECTION_SEP.join(parts)
            row = (nbtype, nbloc, nb.title)
            data.append(row)
            metadata.append((nb.type, nb.name, is_tut))
        return data, metadata

    def is_tree_section(self, key) -> bool:
        return key.startswith(self._section_key_prefix)

    def is_root(self, key) -> bool:
        return key == self._root_key


class Notebook:
    """Interface for metadata of one Jupyter notebook."""

    MAX_TITLE_LEN = 50
    SECTION_SEP = "/"

    def __init__(self, name: str, section: Tuple, path: Path, nbtype="plain"):
        self.name, self._section = name, section
        self._path = path
        self._long_desc = ""
        # Default title of the notebook is its filename but this will be replaced with
        # the title in the notebook, if one can be found
        self._short_desc = self._shorten_title(name)
        self._lines = []
        self._get_description()
        self._type = nbtype

    @classmethod
    def _shorten_title(cls, text: str) -> str:
        maxlen = cls.MAX_TITLE_LEN - 2  # take off 2 more for 2 dots
        if len(text) <= maxlen:
            result = text
        else:
            result = f"{text[:maxlen]}.."
            _log.debug(f"shortened '{text}' to '{result}")
        return result

    @property
    def section(self) -> str:
        return self.SECTION_SEP.join(self._section)

    @property
    def section_parts(self):
        return tuple((s for s in self._section))

    @property
    def title(self) -> str:
        return self._short_desc

    @property
    def description(self) -> str:
        return self._long_desc

    @property
    def description_lines(self) -> List[str]:
        return self._lines

    @property
    def type(self) -> str:
        return self._type

    @property
    def path(self) -> Path:
        return self._path

    def _get_description(self):
        desc = False
        with self._path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        cells = data[NB_CELLS]
        if len(cells) > 0:
            for c1 in cells:
                if c1["cell_type"] == "markdown" and "source" in c1 and c1["source"]:
                    self._long_desc = "".join(c1["source"])
                    self._lines = c1["source"]
                    for line in self._lines:
                        if line.strip().startswith("#"):
                            last_pound = line.rfind("#")
                            self._short_desc = self._shorten_title(
                                line[last_pound + 1 :].strip()
                            )
                            break
                    desc = True
                    break
        if not desc:
            self._short_desc, self._long_desc = "No description", "No description"
            self._lines = [self._short_desc]


class Jupyter:
    """Run Jupyter notebooks."""

    COMMAND = "jupyter"

    def __init__(self, lab=False):
        self._app = "lab" if lab else "notebook"

    def open(self, nb_path: Path):
        """Open notebook in a browser.

        Args:
            nb_path: Path to notebook (.ipynb) file.

        Returns:
            None
        """
        _log.info(f"(start) open notebook at path={nb_path}")
        proc = Popen([self.COMMAND, self._app, str(nb_path)], stderr=PIPE)
        _log.info(f"(end) opened notebook at path={nb_path}")

    def stop(self):
        """Stop all running notebooks.

        Returns:
            None
        """
        with Popen([self.COMMAND, self._app, "stop", "foo"], stderr=PIPE) as proc:
            ports = []
            for line in proc.stderr:
                m = re.match(r".*- (\d+)", line.decode("utf-8").strip())
                if m:
                    ports.append(m.group(1))

        _log.info(f"Stop servers running on ports: {', '.join(ports)}")
        for port in ports:
            self._stop(int(port))

    def _stop(self, port):
        _log.info(f"(start) stop running notebook, port={port}")
        p = Popen([self.COMMAND, self._app, "stop", str(port)], stderr=DEVNULL)
        try:
            p.wait(timeout=5)
            _log.info(f"(end) stop running notebook, port={port}: Success")
        except TimeoutExpired:
            _log.info(f"(end) stop running notebook, port={port}: Timeout")
