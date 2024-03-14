"""
Graphical examples browser
"""
# stdlib
from importlib import resources

if not hasattr(resources, "files"):
    # importlib.resources.files() added in Python 3.9
    import importlib_resources as resources
from datetime import datetime
import json
import logging
from operator import attrgetter
from pathlib import Path
import re
from subprocess import Popen, DEVNULL, PIPE, TimeoutExpired
from typing import Tuple, List, Dict, Iterable
import sys

# third-party
from blessed import Terminal

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


def setup_logger(log: logging.Logger = None):
    log_file = None
    if log is None:
        log = logging.getLogger(__name__)
    else:
        log.handlers = []
    log_dir = Path("~").expanduser() / ".idaes" / "logs"
    try:
        log_dir.mkdir(exist_ok=True)
        t = datetime.now()
        timestamp = (
            f"{t.year}{t.month:02d}{t.day:02d}{t.hour:02d}{t.minute:02d}{t.second:02d}"
        )
        log_file = log_dir / f"browse_{timestamp}.log"
        handler = logging.FileHandler(log_file)
    except FileNotFoundError:
        handler = None  # XXX: silent failure
    if handler:
        handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(asctime)s %(module)s - %(message)s")
        )
        log.addHandler(handler)
        log.propagate = False
    return log, log_file


_log, _log_file = setup_logger()


def get_log():
    return _log


def get_log_file():
    return _log_file


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
                _log.debug(f"find_notebook_dir: root_path={p}")
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
                                line[(last_pound + 1) :].strip()
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
        _log.info(f"begin: open-notebook path={nb_path}")
        proc = Popen([self.COMMAND, self._app, str(nb_path)], stderr=PIPE)
        _log.info(f"end: open-notebook path={nb_path}")

    def stop(self):
        """Stop all running notebooks.

        Returns:
            None
        """
        # run a Jupyter command line that will list open ports
        # use 'foo' as the invalid port to stop, so it cannot match
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
        _log.info(f"begin: stop-running-notebook port={port}")
        p = Popen([self.COMMAND, self._app, "stop", str(port)], stderr=DEVNULL)
        try:
            p.wait(timeout=5)
            _log.info(f"end: stop-running-notebook port={port}: Success")
        except TimeoutExpired:
            _log.info(f"end: stop-running-notebook port={port}: Timeout")


# -------------
#  Terminal UI
# -------------


def blessed_gui(notebooks, use_lab=True, stop_notebooks_on_quit=True):
    """Create and run a terminal-based UI."""
    _log.info(f"begin: run-ui")
    jupyter_params = {"lab": use_lab}
    notebook_list = list(notebooks.notebooks.values())
    ui = TerminalUI(notebook_list, jupyter_params)
    try:
        ui.run()
    except KeyboardInterrupt:
        pass
    if stop_notebooks_on_quit:
        ui.stop_notebooks()
    _log.info(f"end: run-ui")
    return 0


def prn(*args):
    """Alias to print with no newline at the end."""
    print(*args, end="")


def _flush():
    """Alias to flush the standard output stream."""
    sys.stdout.flush()


class TerminalUI:
    """
    Terminal-based UI for selecting and running example Jupyter Notebooks.
    """

    # more convenient tuple for working with a notebook
    class Nb:
        def __init__(
            self,
            name: str,
            title: str,
            path: str,
            types: List[str],
            desc_lines: List[str],
        ):
            self.name = name
            self.title = title
            self.path = path
            self.types = types
            self.desc_lines = desc_lines

        @property
        def tutorial(self):
            return "Yes" if Ext.SOL.value in self.types else "No"

    class NbMeta:
        def __init__(self):
            self.fields = ("Author", "Maintainer", "Updated")
            self._data = {k: "?" for k in self.fields}

        def extract(self, line):
            for field in self.fields:
                if line.startswith(field + ":"):
                    _, value = line.split(":")
                    self._data[field] = value.strip()
                    return True
            return False

        def __setitem__(self, key, value):
            self._data[key] = value

        @property
        def author(self):
            return self._data["Author"]

        @property
        def maintainer(self):
            return self._data["Maintainer"]

        @property
        def updated(self):
            return self._data["Updated"]

    display_columns = ("name", "title", "tutorial")
    max_display_widths = {"title": 50, "name": 20, "tutorial": 8, "dialog": 60}
    left_gutter = 4
    row_num_fmt = "{0:" + str(left_gutter - 1) + "d}"

    def __init__(self, notebooks: List[Notebook], jupyter_params: Dict):
        self._nb_items, self._col_widths = self._create_items(notebooks)
        self._term = Terminal()

        # colors
        self.c_norm = self._term.white_on_black
        self.c_rev = self._term.black_on_white
        self.c_dim = self._term.bright_black
        self.c_dim_rev = self._term.white_on_bright_black
        self.c_div = self.c_ftr = self._term.magenta
        self.c_hdr = self._term.green
        self.c_dim_sel = self._term.bright_black_on_white
        self.c_norm_sel = self._term.black_on_white
        self.c_box_border = self._term.black_on_blue
        self.c_box_ok = self._term.green
        self.c_box_cancel = self._term.red
        self.c_box_optc = self._term.green
        self.c_dlg_title = self._term.yellow
        self.c_author = self._term.green
        self.c_maintainer = self._term.yellow
        self.c_date = self._term.cyan
        self.c_subsec = self._term.bright_blue
        self.c_sec = self._term.bright_blue

        # displayed rows range and current selected row
        self._start, self._cur, self._end = 0, 0, 0
        self._n = len(self._nb_items)

        # change made that requires refresh
        self._changed = True

        # quit app
        self._done = False

        # Jupyter runner & settings
        self._jupyter = Jupyter(**jupyter_params)

    def run(self):
        """Run this terminal-based UI."""
        self._event_loop()

    def stop_notebooks(self):
        _log.info("begin: stop-running-notebooks")
        self._jupyter.stop()
        _log.info("end: stop-running-notebooks")

    def _create_items(self, nb_list: List[Notebook]):
        """Create Nb items and also compute max column widths."""
        col_max = {c: 0 for c in self.display_columns}
        nb_map = {}
        for nb in nb_list:
            nb_id = nb.name
            if nb_id in nb_map:
                nb_map[nb_id].types.append(nb.type)
            else:
                nb_item = self.Nb(
                    nb.name, nb.title, str(nb.path), [nb.type], nb.description_lines
                )
                for k in col_max:
                    col_max[k] = max(col_max[k], len(getattr(nb_item, k)) + 1)
                nb_map[nb_id] = nb_item
        for k in self.display_columns:
            col_max[k] = min(self.max_display_widths[k], col_max[k])
        return list(nb_map.values()), col_max

    def _table_height(self):
        """Get target height of the table."""
        return (self._term.height - 20) - 3  # header, divider, footer

    def _event_loop(self):
        """Main event loop for the app."""
        t = self._term

        with t.fullscreen():
            while not self._done:
                if self._changed:
                    # XXX: dumb refresh on every change
                    print(t.clear())
                    self._end = self._table_height() + self._start
                    self._show_table()
                    self._show_divider()
                    self._show_details()
                    self._show_footer()
                    _flush()
                    self._changed = False
                self._process_input()

    def _show_table(self):
        """Display the notebooks in a table."""
        t = self._term
        prn(t.move_xy(self.left_gutter, 0))

        # table header
        for hdr in self.display_columns:
            width = self._col_widths[hdr]
            s = hdr.title()
            prn(f"{self.c_hdr}{s}{self.c_norm}{t.move_right(width - len(s) + 1)}")
        print()

        # table body
        end_ = min(self._end, len(self._nb_items))
        for row in range(self._start, end_):
            # Pick colors depending on whether row is selected
            if row == self._cur:
                dim, norm = self.c_dim_sel, self.c_norm_sel
            else:
                dim, norm = self.c_dim, self.c_norm
            # Calculate and print row number
            row_num = self.row_num_fmt.format(row + 1)
            prn(f"{dim}{row_num}{norm} ")
            # Print row contents
            item = self._nb_items[row]
            for hdr in self.display_columns:
                width = self._col_widths[hdr]
                s = getattr(item, hdr)
                if len(s) >= width:
                    s, padding = s[:width], 1
                else:
                    padding = width - len(s) + 1
                prn(f"{s}{' ' * padding}")
            # Move down to next row
            print(self.c_norm)

    def _show_divider(self):
        """ "Show a divider between the table of notebooks and notebook details."""
        y = self._table_height() + 1
        t = self._term
        w = t.width
        num = len(self._nb_items)
        msg = f"Rows {self._start + 1} - {self._end} out of {num}"
        msg += " | Move with arrow Up/Down and PgUp/PgDn"
        rpad = " " * (t.width - len(msg))
        print(f"{t.move_xy(0, y)}{self.c_div}{msg}{rpad}{self.c_norm}")

    def _show_details(self):
        """Show details of selected notebook on the main screen."""
        _log.info("begin: show-details")
        nb = self._nb_items[self._cur]
        t, y = self._term, self._table_height() + 2
        height = t.height - y - 1

        # Print Path at top
        path = Path(nb.path).name[: t.width]
        prn(f"{t.move_xy(0, y)}Path: {self.c_dim}{path}{self.c_norm}")
        y += 1

        # Print description meta
        lines = nb.desc_lines[:height]
        meta, lines = self._extract_desc_meta(lines)
        s = (
            f"{self.c_author}{meta.author}{self.c_norm}"
            f" / {self.c_maintainer}{meta.maintainer}{self.c_norm}"
            f" - {self.c_date}{meta.updated}{self.c_norm}"
        )
        prn(f"{t.move_xy(0, y)}{s}")
        # length of that header discounting all the terminal escape codes
        line_len = len(meta.author) + len(meta.maintainer) + len(meta.updated) + 6
        prn(f"{t.move_xy(0, y + 1)}{self.c_dim}{'-' * line_len}")
        y += 2

        # Print description lines
        i = 0
        for line in lines:
            s = self._desc_line(line)
            if s:
                prn(f"{t.move_xy(0, y + i)}{s}")
                i += 1

    def _extract_desc_meta(self, lines) -> Tuple[NbMeta, List[str]]:
        t = self._term
        non_meta_lines = []
        meta = self.NbMeta()
        to_find = len(meta.fields)
        for line in lines:
            if to_find > 0 and meta.extract(line.strip()):
                to_find -= 1
            else:
                non_meta_lines.append(line)
        return meta, non_meta_lines

    def _desc_line(self, line: str) -> str:
        t = self._term
        line = line.strip()[: t.width - 1]
        if line.startswith("##"):
            line = f"{self.c_subsec}{line}{self.c_norm}"
        elif line.startswith("#"):
            line = f"{self.c_sec}{line}{self.c_norm}"
        elif re.match(r"(<.*>)|(<.*/.*>)", line):  # HTML
            line = ""
        elif line == "$$":  # Latex math
            line = ""
        return line

    def _show_footer(self):
        """Show a footer on the main screen."""
        t = self._term
        prn(f"{t.move_xy(0, t.height)}{self.c_ftr}Press 'Enter' to run, 'q' to Quit")

    def _process_input(self):
        """Get input from the user while in the table of notebooks."""
        with self._term.cbreak():
            val = self._term.inkey(timeout=1)
            if val:
                if val.is_sequence:
                    if val.code == self._term.KEY_UP:
                        self._select(-1)
                    elif val.code == self._term.KEY_DOWN:
                        self._select(1)
                    elif val.code == self._term.KEY_PGUP:
                        self._select(-10)
                    elif val.code == self._term.KEY_PGDOWN:
                        self._select(10)
                    elif val.code == self._term.KEY_ENTER:
                        self._dialog(self._nb_items[self._cur])
                        self._changed = True
                elif val == "q":
                    self._done = True

    def _select(self, d):
        """Select a row in the table of notebooks."""
        cur = self._cur
        # calculate new row, clipped to number of rows
        if d > 0:
            if cur < self._n:
                cur = min(cur + d, self._n - 1)
        elif d < 0:
            if cur > 0:
                cur = max(cur + d, 0)

        if cur == self._cur:
            return  # nothing to do, don't set self._changed

        if d < 0 and cur < self._start:
            self._start = cur
            self._end = self._start + self._table_height()
        elif d > 0 and cur >= self._end:
            self._end = cur
            self._start = self._end - self._table_height() + 1

        self._cur = cur
        self._changed = True

    def _dialog(self, nb: Nb):
        """Dialog box for selecting and running a notebook."""
        t = self._term

        # Title of dialog box is notebook name
        title = nb.name

        # Build menu of notebook run options and corresponding paths
        nb_ext_name = {Ext.USER: "User", Ext.SOL: "Solution", Ext.EX: "Exercise"}
        if Ext.SOL.value in nb.types:
            options = (("s", nb_ext_name[Ext.SOL]), ("u", nb_ext_name[Ext.USER]), ("", nb_ext_name[Ext.EX]))
        else:
            options = (("", nb_ext_name[Ext.USER]),)

        # Choose box size
        ul_x, ul_y = 4, 4
        inner_width = self.max_display_widths["dialog"] - 2  # subtract 2 for border
        title = title[:inner_width]
        lr_x, lr_y = min(t.width - 1, ul_x + inner_width + 2), min(
            t.height - 2, ul_y + 5 + len(options)
        )

        # Draw box border & fill
        bw = inner_width + 2
        prn(self.c_box_border)
        prn(f"{t.move_xy(ul_x, ul_y)}{' ' * bw}")  # top
        prn(f"{t.move_xy(ul_x, lr_y)}{' ' * bw}")  # bottom
        fill_spc = " " * inner_width
        for y in range(ul_y + 1, lr_y):
            prn(
                f"{t.move_xy(ul_x, y)}{self.c_box_border} {self.c_norm}{fill_spc}{self.c_box_border} "
            )
        prn(self.c_norm)

        # Add action buttons
        y = lr_y - 1
        prn(
            f"{t.move_xy(ul_x + 2, y)}{self.c_dim}Press key for desired Notebook{self.c_norm}"
        )
        prn(f"{t.move_xy(lr_x - 14, y)}{self.c_box_cancel}[Esc=CANCEL]{self.c_norm}")

        # Add title
        n = len(title)
        x_offs = (inner_width - n) // 2 + 1
        prn(
            f"{t.move_xy(ul_x + x_offs, ul_y + 1)}{self.c_dlg_title}{title}{self.c_norm}"
        )
        self._changed = True

        # Add options
        y = ul_y + 3  # line after, line after title
        x = ul_x + 4
        for i, (c, name) in enumerate(options):
            if c == "":
                keypress = "Enter"
            else:
                keypress = f"{c.upper()}    "
            prn(
                f"{t.move_xy(x, y + i)}{self.c_box_optc}{keypress}{self.c_norm}: Run {self.c_box_optc}{name}{self.c_norm} Notebook"
            )

        _flush()

        # Read input for the dialog box
        with t.cbreak():
            nb_choice = None  # None = invalid
            while nb_choice is None:
                val = t.inkey(timeout=60)
                if val:
                    if val.code == t.KEY_ESCAPE:
                        nb_choice = ""  # special choice for cancel
                        break
                    for c, name in options:
                        if (c == "" and val.code == t.KEY_ENTER) or (
                            not val.is_sequence and val.lower() == c
                        ):
                            nb_choice = name
                            break

        if nb_choice:
            # Map chosen name back to an extension
            nb_name_ext = {v: k for k, v in nb_ext_name.items()}
            nb_ext = nb_name_ext[nb_choice]

            # Get path to notebook and try to run it
            path = self._notebook_path(nb_ext.value, nb)
            self._jupyter.open(path)

    @staticmethod
    def _notebook_path(ext, nb: Nb) -> Path:
        # Transform name: /path/to/notebook_usr.ipynb -> /path/to/notebook_<ext>.ipynb
        orig_path = Path(nb.path)
        stem, suffix = orig_path.stem, orig_path.suffix
        # change final _<ext>
        try:
            new_name = stem[: stem.rfind("_") + 1] + ext
        except ValueError:
            raise (
                f"Invalid notebook name '{orig_path}': "
                f"missing final '_<ext>' before suffix"
            )
        new_name += suffix
        # rebuild path
        path = orig_path.parent / new_name

        return path
