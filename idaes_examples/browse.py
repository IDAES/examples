"""
Graphical examples browser
"""
# stdlib
from importlib import resources

if not hasattr(resources, "files"):
    # importlib.resources.files() added in Python 3.9
    import importlib_resources as resources
import json
import logging
from logging.handlers import RotatingFileHandler
from multiprocessing import Process
from operator import attrgetter
from pathlib import Path
import re
from subprocess import Popen, DEVNULL, PIPE, TimeoutExpired
import time
from typing import Tuple, List, Dict, Iterable

try:
    from ctypes import windll
except:
    windll = None

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
        if Notebook.SECTION_SEP in section:
            section_tuple = tuple(section.split(Notebook.SECTION_SEP))
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
            "<div style='font-size: 80%; "
            'font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;\'>'
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


def gui(notebooks, use_lab=False, stop_notebooks_on_quit=False):
    _log.info(f"begin:run-gui")
    PySG.theme("Material2")

    if windll:
        windll.shcore.SetProcessDpiAwareness(1)

    def get_font(size, style=None):
        f = ["Arial", size]
        if style:
            f.append(style)
        return tuple(f)

    # nb_tree = notebooks.as_tree()
    nb_table, nb_table_meta = notebooks.as_table()
    # print(f"@@TABLE={nb_table}\n\nMETA={nb_table_meta}")

    primary_bg = "#2092ed"

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
        font=get_font(11),
        **sbar_kwargs,
    )
    description_frame = PySG.Frame(
        "Description", layout=[[description_widget]], expand_y=True, expand_x=True
    )

    columns = [0, 0, 0]
    for row in nb_table:
        for col_index in range(2):
            w = len(row[col_index]) // 2
            if columns[col_index] < w:
                columns[col_index] = w
        w = len(row[2])
        if columns[2] < w:
            columns[2] = w

    nb_widget = PySG.Table(
        values=nb_table,
        # without added spaces, the headings will be centered instead of left-aligned
        headings=["Type" + " " * 40, "Location" + " " * 80, "Title" + " " * 160],
        expand_x=True,
        expand_y=False,
        justification="left",
        enable_click_events=True,
        alternating_row_color="#def",
        col_widths=columns,
        auto_size_columns=False,
        selected_row_colors=("white", primary_bg),
        header_text_color="black",
        header_font=get_font(11, style="bold"),
        font=get_font(11),
        header_relief=PySG.RELIEF_FLAT,
        header_background_color="#eee",
    )

    open_buttons = {}
    for ext in Ext.USER, Ext.SOL, Ext.EX:
        if ext == Ext.USER:
            label = "Open Example"
        elif ext == Ext.SOL:
            label = "Open Solution"
        else:
            label = "Open Exercise"
        open_buttons[ext] = PySG.Button(
            label,
            tooltip=f"Open selected notebook",
            button_color=("white", primary_bg),
            disabled_button_color=("#696969", "#EEEEEE"),
            border_width=0,
            # auto_size_button=True,
            size=len(label),
            key=f"open+{ext.value}",
            disabled=True,
            pad=(20, 20),
            use_ttk_buttons=True,
            font=get_font(11),
        )

    quit_button = PySG.Button(
        "Quit",
        tooltip="Quit the application",
        button_color=("white", primary_bg),
        border_width=0,
        key="quit",
        disabled=False,
        pad=(10, 10),
        auto_size_button=False,
        use_ttk_buttons=True,
        font=get_font(11),
    )

    intro_nb, flowsheet_nb = "intro", "flowsheet"
    start_notebook_paths = {}
    for key in notebooks.keys():
        sect, name, ext = key
        # print(key)
        if sect[0] == "docs" and sect[1] == "tut":
            if name == "introduction" and ext == Ext.USER.value:
                start_notebook_paths[intro_nb] = notebooks[key].path
            elif name == "hda_flowsheet" and ext == Ext.SOL.value:
                start_notebook_paths[flowsheet_nb] = notebooks[key].path

    # Find the start-here notebooks and add buttons for them
    start_here_panel = []
    # Be robust to not-found notebooks
    if len(start_notebook_paths) == 0:
        _log.warning("Could not find 'Start here' notebooks")
    else:
        start_here_panel.append(PySG.Text("Not sure where to start? Try one of these:"))
        sh_kwargs = dict(
            text_color=primary_bg,
            font=get_font(11, style="underline"),
            enable_events=True,
        )
        for sh_nb, text in ((intro_nb, "Introduction"), (flowsheet_nb, "Flowsheet")):
            if sh_nb in start_notebook_paths:
                button = PySG.Text(text, key=f"starthere_{sh_nb}", **sh_kwargs)
                start_here_panel.append(button)
                if text == "Introduction":
                    start_here_panel.append(PySG.Text("for an IDAES overview or"))
                else:
                    start_here_panel.append(PySG.Text("for a flowsheet tutorial"))

    instructions = PySG.Text(
        "Select a notebook and then select 'Open' to open it in Jupyter"
    )

    layout = [
        [instructions],
        [nb_widget],
        [description_frame],
        [
            PySG.Text("Actions:"),
            open_buttons[Ext.USER],
            open_buttons[Ext.EX],
            open_buttons[Ext.SOL],
            PySG.P(),
            quit_button,
        ],
    ]

    if start_here_panel:
        layout.insert(0, [PySG.VerticalSeparator(pad=(0, 20)), start_here_panel])

    # create main window
    w, h = PySG.Window.get_screen_size()
    capped_w = min(w, 3840)
    width = int(capped_w // 1.4)
    height = int(min(h - 10, width // 2))

    window = PySG.Window(
        "IDAES Notebook Browser",
        layout,
        size=(width, height),
        finalize=True,
        icon=IDAES_ICON_B64,
        font=get_font(11),
        text_justification="left",
    )

    nbdesc = NotebookDescription(notebooks, window["Description"].Widget)
    # print(f"@@ NOTEbOOKS: {notebooks.notebooks}")
    # Event Loop to process "events" and get the "values" of the inputs
    jupyter = Jupyter(lab=use_lab)
    shown = None
    try:
        while True:
            _log.debug("Wait for event")
            event, values = window.read()
            _log.debug("Event detected")
            # if user closes window or clicks cancel
            if event == PySG.WIN_CLOSED or event == "quit":
                break
            # print(event, values)
            if isinstance(event, int):
                _log.debug(f"Unhandled event: {event}")
            elif isinstance(event, tuple):
                if event[1] == "+CLICKED+":
                    row_index = event[2][0]
                    if row_index is not None:
                        data_row = nb_table[row_index]
                        meta_row = nb_table_meta[row_index]
                        section = data_row[1]
                        name = meta_row[1]
                        type_ = Ext.USER.value
                        nbdesc.show(section, name, type_)
                        shown = (section, name, meta_row[0])
                        is_tut = meta_row[2]
                        open_buttons[Ext.USER].update(disabled=is_tut)
                        open_buttons[Ext.EX].update(disabled=not is_tut)
                        open_buttons[Ext.SOL].update(disabled=not is_tut)
            elif isinstance(event, str) and event.startswith("open+"):
                if shown:
                    path = nbdesc.get_path(*shown)
                    jupyter.open(path)
            elif event.startswith("starthere"):
                what = event.split("_")[-1]
                path = start_notebook_paths[what]
                print(path)
                jupyter.open(path)
    except KeyboardInterrupt:
        print("Stopped by user")

    if stop_notebooks_on_quit:
        print("** Stop running notebooks")
        try:
            jupyter.stop()
        except KeyboardInterrupt:
            pass
    _log.info("Close main window")
    window.close()
    _log.info(f"end:run-gui")
    return 0


IDAES_ICON_B64 = b"iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAAwnpUWHRSYXcgcHJvZmlsZSB0eXBlIGV4aWYAAHjabVBRDsMgCP3nFDuC8KjF49jVJbvBjj8stqnZXiI8eeSJUPu8X/ToEFbSZbVcck4OLVqkOrEUqEfkpEc8IKfGc50uQbwEz4ir5dF/1vkyiFSdLTcjew5hm4Wi1wSzkURCn6jzfRiVYQQJgYdBjW+lXGy9f2FraYbFoR7U5rF/7qtvb1/8HYg0MJJHQGMA9ANCdZI9MswbGeq8ozqzYeYL+benE/QF8Z1ZJeKi9MoAAAGEaUNDUElDQyBwcm9maWxlAAB4nH2RPUjDQBzFX1O1IhVBK4g4ZKhO7aIijqWKRbBQ2gqtOphc+iE0aUhSXBwF14KDH4tVBxdnXR1cBUHwA8TVxUnRRUr8X1JoEePBcT/e3XvcvQOERoWpZlcMUDXLSCfiYi6/IgZe0YNBDENERGKmnswsZOE5vu7h4+tdlGd5n/tz9CsFkwE+kTjGdMMiXiee2bR0zvvEIVaWFOJz4ohBFyR+5Lrs8hvnksMCzwwZ2fQccYhYLHWw3MGsbKjE08RhRdUoX8i5rHDe4qxWaqx1T/7CYEFbznCd5hgSWEQSKepIRg0bqMBClFaNFBNp2o97+Ecdf4pcMrk2wMgxjypUSI4f/A9+d2sWpybdpGAc6H6x7Y9xILALNOu2/X1s280TwP8MXGltf7UBzH6SXm9r4SNgYBu4uG5r8h5wuQOMPOmSITmSn6ZQLALvZ/RNeWDoFuhbdXtr7eP0AchSV0s3wMEhMFGi7DWPd/d29vbvmVZ/P+l6ctZZqXqtAAANdmlUWHRYTUw6Y29tLmFkb2JlLnhtcAAAAAAAPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4KPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iWE1QIENvcmUgNC40LjAtRXhpdjIiPgogPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4KICA8cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIgogICAgeG1sbnM6eG1wTU09Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8iCiAgICB4bWxuczpzdEV2dD0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL3NUeXBlL1Jlc291cmNlRXZlbnQjIgogICAgeG1sbnM6ZGM9Imh0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvIgogICAgeG1sbnM6R0lNUD0iaHR0cDovL3d3dy5naW1wLm9yZy94bXAvIgogICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFkb2JlLmNvbS90aWZmLzEuMC8iCiAgICB4bWxuczp4bXA9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8iCiAgIHhtcE1NOkRvY3VtZW50SUQ9ImdpbXA6ZG9jaWQ6Z2ltcDpmOTVjOGExOC1hYzVmLTRiMTktYjE5ZS0xM2VlYzAwYWRjY2MiCiAgIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6MzJlZDk2NjMtZTg2Yi00ZDZkLWFkMmQtODk1NTAzNTIwODVjIgogICB4bXBNTTpPcmlnaW5hbERvY3VtZW50SUQ9InhtcC5kaWQ6NWMyMjViYzgtOTNiYi00M2NlLTliMDctZDU0ZDVhMjNkOTQ0IgogICBkYzpGb3JtYXQ9ImltYWdlL3BuZyIKICAgR0lNUDpBUEk9IjIuMCIKICAgR0lNUDpQbGF0Zm9ybT0iV2luZG93cyIKICAgR0lNUDpUaW1lU3RhbXA9IjE2ODcxMjQwMzEzNzA0ODkiCiAgIEdJTVA6VmVyc2lvbj0iMi4xMC4zNCIKICAgdGlmZjpPcmllbnRhdGlvbj0iMSIKICAgeG1wOkNyZWF0b3JUb29sPSJHSU1QIDIuMTAiCiAgIHhtcDpNZXRhZGF0YURhdGU9IjIwMjM6MDY6MThUMTQ6MzM6NDgtMDc6MDAiCiAgIHhtcDpNb2RpZnlEYXRlPSIyMDIzOjA2OjE4VDE0OjMzOjQ4LTA3OjAwIj4KICAgPHhtcE1NOkhpc3Rvcnk+CiAgICA8cmRmOlNlcT4KICAgICA8cmRmOmxpCiAgICAgIHN0RXZ0OmFjdGlvbj0ic2F2ZWQiCiAgICAgIHN0RXZ0OmNoYW5nZWQ9Ii8iCiAgICAgIHN0RXZ0Omluc3RhbmNlSUQ9InhtcC5paWQ6YjVlMTk3NGYtYTNjMS00ZTVhLTgxOGEtNWQ5YWE3ZTBlZmNmIgogICAgICBzdEV2dDpzb2Z0d2FyZUFnZW50PSJHaW1wIDIuMTAgKFdpbmRvd3MpIgogICAgICBzdEV2dDp3aGVuPSIyMDIzLTA2LTE4VDE0OjMzOjUxIi8+CiAgICA8L3JkZjpTZXE+CiAgIDwveG1wTU06SGlzdG9yeT4KICA8L3JkZjpEZXNjcmlwdGlvbj4KIDwvcmRmOlJERj4KPC94OnhtcG1ldGE+CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgICAgICAgICAgICAKPD94cGFja2V0IGVuZD0idyI/Pl/FyzMAAAAGYktHRAD/AP8A/6C9p5MAAAAJcEhZcwAACxMAAAsTAQCanBgAAAAHdElNRQfnBhIVITObZ/5AAAAPz0lEQVRYw81YeXRV1bn/9hnvPXcecm+SC5khkIQhiUJABFQgUQzS+iACLqDyRAWcusTniGVVLNahVqHPsbb0SVUEwxRCBkLCKAEFJIQMJGQiubnJne+5Z97vD8VaG1/fc9n2nf/OXt/w29+09/4h+JG+Zz6qQVfNmdcRCj/0bmlu549lF/0YRtZUtaT2Y+er2VbMiZKq+gW1xSYMPPdaaUH0Xwrw8domyxXF+aQPzGtExJpymNDh1IGGOXTWlDsHYsTDQUn5AzfY/PvfLZuj/lAfxA9RWvdBFbWiundlCNl25NnIWyREmxAASCpyG4Sw9sR1SR+Po7zFiXoqUUvO27+qsnP2+t2H0T8lgsv3d8xgOcNjVpDO3aK019EON5yUEt8MKqTjRv1wQ+/JirI1a9cp1+Rfqm9N7CesL0UkVaEVftPvijPb/yEA/31fcwo2OJ6b5NAt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"
