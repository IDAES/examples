"""
Graphical examples browser
"""
# stdlib
from importlib import resources
import json
import logging
from logging.handlers import RotatingFileHandler
from operator import attrgetter
from pathlib import Path
import re
from subprocess import Popen, PIPE, TimeoutExpired
from typing import Tuple, List, Dict

# third-party
import markdown
import PySimpleGUI as PySG
from tkhtmlview import html_parser

# package
import idaes_examples
from idaes_examples.util import (
    find_notebooks,
    read_toc,
    NB_CELLS,
    Ext,
    src_suffix_len,
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
    """Log to a file, unless none can be opened.
    """
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
        logging.Formatter("[%(levelname)s] %(asctime)s %(name)s::%(module)s "
                          "- %(message)s")
    )
    _log.addHandler(handler)


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
            if p.stem == "nb":
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
        if user_dir:
            _log.debug(f"Loading notebooks from provided directory: {srcdir}")
            self._root = Path(srcdir)
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
        self._tree = self._as_tree()

    def _add_notebook(self, path: Path, **kwargs):
        name = path.stem[:-src_suffix_len]
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

    def as_tree(self) -> PySG.TreeData:
        """Get notebooks as a tree suitable for displaying in a PySimpleGUI
        Tree widget.
        """
        return self._tree

    def _as_tree(self) -> PySG.TreeData:
        td = PySG.TreeData()

        # organize notebooks hierarchically
        data = {}
        for nb in self._sorted_values:
            if nb.section not in data:
                data[nb.section] = {}
            if nb.name not in data[nb.section]:
                data[nb.section][nb.name] = []
            data[nb.section][nb.name].append(nb)

        # copy hierarchy into an sg.TreeData object
        td.insert("", text="Notebooks", key=self._root_key, values=[])
        for section in data:
            section_key = f"{self._section_key_prefix}_{section}"
            td.insert(self._root_key, key=section_key, text=section, values=[])
            for name, nblist in data[section].items():
                base_key = None
                # Make an entry for the base notebook
                for nb in nblist:
                    if nb.type == Ext.USER.value:
                        base_key = f"nb+{section}+{nb.name}+{nb.type}"
                        td.insert(
                            section_key, key=base_key, text=nb.title, values=[nb.path]
                        )
                        break
                # Make sub-entries for examples, tutorials, etc. (if there are any)
                if len(nblist) > 1:
                    for nb in nblist:
                        if nb.type != Ext.USER.value:
                            sub_key = f"nb+{section}+{nb.name}+{nb.type}"
                            # The name of the sub-entry is its type, since it will be
                            # visually listed under the title of the base entry.
                            subtitle = nb.type.title()
                            td.insert(
                                base_key, key=sub_key, text=subtitle, values=[nb.path]
                            )

        return td

    def is_tree_section(self, key) -> bool:
        return key.startswith(self._section_key_prefix)

    def is_tree_root(self, key) -> bool:
        return key == self._root_key


class Notebook:
    """Interface for metadata of one Jupyter notebook."""

    def __init__(self, name: str, section: Tuple, path: Path, nbtype="plain"):
        self.name, self._section = name, section
        self._path = path
        self._long_desc, self._short_desc = "", name
        self._lines = []
        self._get_description()
        self._type = nbtype

    @property
    def section(self) -> str:
        return ":".join(self._section)

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
        with self._path.open("r") as f:
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
                            self._short_desc = line[last_pound + 1 :].strip()
                            break
                    desc = True
                    break
        if not desc:
            self._short_desc, self._long_desc = "No description", "No description"
            self._lines = [self._short_desc]


class Jupyter:
    """Run Jupyter notebooks."""

    COMMAND = "jupyter"

    def __init__(self):
        self._ports = set()

    def open(self, nb_path: Path):
        """Open notebook in a browser.

        Args:
            nb_path: Path to notebook (.ipynb) file.

        Returns:
            None
        """
        _log.info(f"(start) open notebook at path={nb_path}")
        p = Popen([self.COMMAND, "notebook", str(nb_path)], stderr=PIPE)
        buf, m, port = "", None, "unknown"
        while True:
            s = p.stderr.read(100).decode("utf-8")
            if not s:
                break
            buf += s
            m = re.search(r"http://.*:(\d{4})/\?token", buf, flags=re.M)
            if m:
                break
        if m:
            port = m.group(1)
            self._ports.add(port)
        _log.info(f"(end) open notebook at path={nb_path} port={port}")

    def stop(self):
        """Stop all running notebooks.

        Returns:
            None
        """
        for port in self._ports:
            self._stop(port)

    @classmethod
    def _stop(cls, port):
        _log.info(f"(start) stop running notebook, port={port}")
        p = Popen([cls.COMMAND, "notebook", "stop", port])
        try:
            p.wait(timeout=5)
            _log.info(f"(end) stop running notebook, port={port}: Success")
        except TimeoutExpired:
            _log.info(f"(end) stop running notebook, port={port}: Timeout")


class NotebookDescription:
    """Show notebook descriptions in a UI widget."""

    def __init__(self, nb: dict, widget):
        self._text = "_Select a notebook to view its description_"
        self._nb = nb
        self._w = widget
        self._html_parser = html_parser.HTMLTextParser()
        self._html()

    def show(self, section: str, name: str, type_: Ext):
        """Show the description in the widget.

        Args:
            section: Section for notebook being described
            name: Name (filename) of notebook
            type_: Type (doc, example, etc.) of notebook

        Returns:
            None
        """
        key = self._make_key(section, name, type_)
        self._text = self._nb[key].description
        # self._print()
        self._html()

    @staticmethod
    def _make_key(section, name, type_):
        if ":" in section:
            section_tuple = tuple(section.split(":"))
        else:
            section_tuple = (section,)
        return section_tuple, name, type_

    def _html(self):
        """Convert markdown source to HTML using the 'markdown' package."""
        m_html = markdown.markdown(
            self._text, extensions=["extra", "codehilite"], output_format="html"
        )
        self._set_html(self._pre_html(m_html))

    @staticmethod
    def _pre_html(text):
        """Pre-process the HTML so it displays more nicely in the relatively crude
        Tk HTML viewer.
        """
        text = re.sub(r"<code>(.*?)</code>", r"<em>\1</em>", text)
        text = re.sub(
            r"<sub>(.*?)</sub>", r"<span style='font-size: 50%'>\1</span>", text
        )
        text = re.sub(r"<h1>(.*?)</h1>", r"<h1 style='font-size: 120%'>\1</h1>", text)
        text = re.sub(r"<h2>(.*?)</h2>", r"<h2 style='font-size: 110%'>\1</h2>", text)
        text = re.sub(r"<h3>(.*?)</h3>", r"<h3 style='font-size: 100%'>\1</h3>", text)
        return (
            f"<div style='font-size: 80%; "
            f'font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;\'>'
            f"{text}</div>"
        )

    def _set_html(self, html, strip=True):
        w = self._w
        prev_state = w.cget("state")
        w.config(state=PySG.tk.NORMAL)
        w.delete("1.0", PySG.tk.END)
        w.tag_delete(w.tag_names)
        self._html_parser.w_set_html(w, html, strip=strip)
        w.config(state=prev_state)

    def get_path(self, section, name, type_) -> Path:
        key = self._make_key(section, name, type_)
        return self._nb[key].path


# -------------
#     GUI
# -------------

FONT = ("Helvetica", 11)


def gui(notebooks):
    _log.info(f"begin:run-gui")
    PySG.theme("Material2")

    nb_tree = notebooks.as_tree()

    sbar_kwargs = dict(
        sbar_trough_color=PySG.theme_background_color(),
        sbar_background_color="lightgrey",
        sbar_frame_color="grey",
        sbar_arrow_color="grey",
    )
    description_widget = PySG.Multiline(
        expand_y=True,
        expand_x=True,
        write_only=True,
        background_color="white",
        key="Description",
        **sbar_kwargs
    )
    description_frame = PySG.Frame(
        "Description", layout=[[description_widget]], expand_y=True, expand_x=True
    )

    title_max = max(len(t) for t in notebooks.titles())

    nb_widget = PySG.Tree(
        nb_tree,
        border_width=0,
        headings=[],
        col0_width=title_max * 5 // 6,
        auto_size_columns=True,
        select_mode=PySG.TABLE_SELECT_MODE_EXTENDED,
        key="-TREE-",
        show_expanded=True,
        expand_y=True,
        expand_x=True,
        enable_events=True,
        font=FONT,
        vertical_scroll_only=True,
        header_border_width=0,
        header_background_color="white",
        **sbar_kwargs
    )

    open_widget = PySG.Button(
        "Open",
        tooltip="Open the selected notebook",
        button_color=("white", "#0079D3"),
        disabled_button_color=("#696969", "#EEEEEE"),
        border_width=0,
        key="open",
        disabled=True,
        pad=(10, 10),
        auto_size_button=False,
        use_ttk_buttons=True,
    )
    layout = [
        [
            nb_widget,
            #PySG.Frame("Notebooks", [[nb_widget]], expand_y=True, expand_x=True),
            description_frame,
        ],
        [open_widget],
    ]
    # create main window
    window = PySG.Window(
        "IDAES Notebook Browser", layout, size=(1200, 600), finalize=True,
        #background_color="#F0FFFF"
    )

    nbdesc = NotebookDescription(notebooks, window["Description"].Widget)

    # Event Loop to process "events" and get the "values" of the inputs
    jupyter = Jupyter()
    while True:
        event, values = window.read()
        # if user closes window or clicks cancel
        if event == PySG.WIN_CLOSED or event == "Cancel":
            break
        # print(event, values)
        if isinstance(event, int):
            _log.debug(f"Unhandled event: {event}")
        elif event == "-TREE-":
            what = values.get("-TREE-", [""])[0]
            if notebooks.is_tree_section(what) or notebooks.is_tree_root(what):
                # cannot open a section or the root entry, so disable the button
                window["open"].update(disabled=True)
            elif what:
                _, section, name, type_ = what.split("+")
                nbdesc.show(section, name, type_)
                # make sure open is enabled
                window["open"].update(disabled=False)
        elif event == "open":
            what = values.get("-TREE-", [None])[0]
            if what:
                _, section, name, type_ = what.split("+")
                path = nbdesc.get_path(section, name, type_)
                jupyter.open(path)

    _log.info("Stop running notebooks")
    jupyter.stop()
    _log.info("Close main window")
    window.close()
    _log.info(f"end:run-gui")
    return 0
