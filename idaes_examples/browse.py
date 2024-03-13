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
from operator import attrgetter
from pathlib import Path
import re
from subprocess import Popen, DEVNULL, PIPE, TimeoutExpired
from typing import Tuple, List, Dict, Iterable
import sys
import time


# third-party
import markdown
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

_log = logging.getLogger(__name__)


def set_log(g):
    global _log
    _log = g


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

    # def as_table(self):
    #     tutorials = set()
    #     for nb in self._sorted_values:
    #         if nb.type == Ext.EX.value:
    #             tutorials.add(nb.section_parts)
    #
    #     data = []
    #     metadata = []
    #     for nb in self._sorted_values:
    #         if nb.type != Ext.USER.value:
    #             continue
    #         parts = nb.section_parts
    #         is_tut = parts in tutorials
    #         nbtype = "Tutorial" if is_tut else "Example"
    #         nbloc = Notebook.SECTION_SEP.join(parts)
    #         row = (nbtype, nbloc, nb.title)
    #         data.append(row)
    #         metadata.append((nb.type, nb.name, is_tut))
    #     return data, metadata

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


# class NotebookDescription:
#     """Show notebook descriptions in a UI widget."""
#
#     def __init__(self, nb: dict, widget):
#         self._text = "_Select a notebook to view its description_"
#         self._nb = nb
#         self._w = widget
#         self._html_parser = html_parser.HTMLTextParser()
#         self._html()
#
#     def show(self, section: str, name: str, type_: Ext):
#         """Show the description in the widget.
#
#         Args:
#             section: Section for notebook being described
#             name: Name (filename) of notebook
#             type_: Type (doc, example, etc.) of notebook
#
#         Returns:
#             None
#         """
#         key = self._make_key(section, name, type_)
#         self._text = self._nb[key].description
#         # self._print()
#         self._html()
#
#     @staticmethod
#     def _make_key(section, name, type_):
#         if Notebook.SECTION_SEP in section:
#             section_tuple = tuple(section.split(Notebook.SECTION_SEP))
#         else:
#             section_tuple = (section,)
#         return section_tuple, name, type_
#
#     def _html(self):
#         """Convert markdown source to HTML using the 'markdown' package."""
#         m_html = markdown.markdown(
#             self._text, extensions=["extra", "codehilite"], output_format="html"
#         )
#         self._set_html(self._pre_html(m_html))
#
#     @staticmethod
#     def _pre_html(text):
#         """Pre-process the HTML so it displays more nicely in the relatively crude
#         Tk HTML viewer.
#         """
#         text = re.sub(r"<code>(.*?)</code>", r"<em>\1</em>", text)
#         text = re.sub(
#             r"<sub>(.*?)</sub>", r"<span style='font-size: 50%'>\1</span>", text
#         )
#         text = re.sub(r"<h1>(.*?)</h1>", r"<h1 style='font-size: 120%'>\1</h1>", text)
#         text = re.sub(r"<h2>(.*?)</h2>", r"<h2 style='font-size: 110%'>\1</h2>", text)
#         text = re.sub(r"<h3>(.*?)</h3>", r"<h3 style='font-size: 100%'>\1</h3>", text)
#         return (
#             "<div style='font-size: 80%; "
#             'font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;\'>'
#             f"{text}</div>"
#         )
#
#     def _set_html(self, html, strip=True):
#         w = self._w
#         prev_state = w.cget("state")
#         w.config(state=PySG.tk.NORMAL)
#         w.delete("1.0", PySG.tk.END)
#         w.tag_delete(w.tag_names)
#         self._html_parser.w_set_html(w, html, strip=strip)
#         w.config(state=prev_state)
#
#     def get_path(self, section, name, type_) -> Path:
#         key = self._make_key(section, name, type_)
#         return self._nb[key].path
#

# -------------
#  Text GUI
# -------------


def blessed_gui(notebooks, **kwargs):
    _log.info(f"begin:run-ui")
    ui = TerminalUI(list(notebooks.notebooks.values()))
    try:
        ui.run()
    except KeyboardInterrupt:
        pass
    _log.info(f"end:run-ui")
    return 0


def prn(*args):
    print(*args, end="")


def _flush():
    sys.stdout.flush()


class TerminalUI:
    # more convenient tuple for working with a notebook
    class Nb:
        def __init__(self, name, title, path, types, desc_lines):
            self.name = name
            self.title = title
            self.path = path
            self.types = types
            self.desc_lines = desc_lines

        @property
        def tutorial(self):
            return "Yes" if Ext.SOL.value in self.types else "No"

    display_columns = ("name", "title", "tutorial")
    max_display_widths = {"title": 50, "name": 20, "tutorial": 8, "dialog": 60}
    left_gutter = 4

    def __init__(self, notebooks: List[Notebook]):
        # XXX
        _log.setLevel(logging.DEBUG)

        self._nb_items, self._col_widths = self._create_items(notebooks)
        self._term = Terminal()

        # colors
        self.c_norm = self._term.white_on_black
        self.c_rev = self._term.black_on_white
        self.c_dim = self._term.bright_black
        self.c_div = self.c_ftr = self._term.magenta
        self.c_hdr = self._term.green
        self.c_dim_sel = self._term.bright_black_on_white
        self.c_norm_sel = self._term.black_on_white
        self.c_box_border = self._term.black_on_blue
        self.c_box_ok = self._term.green
        self.c_box_cancel = self._term.red
        self.c_box_optc = self._term.green
        self.c_dlg_title = self._term.yellow

        # displayed rows range and current selected row
        self._start, self._cur, self._end = 0, 0, 0
        self._n = len(self._nb_items)

        # change made that requires refresh
        self._changed = True

        # quit app
        self._done = False

    def run(self):
        self._event_loop()

    def _create_items(self, nb_list: List[Notebook]):
        "Create Nb items and also compute max column widths."
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
        return (self._term.height - 20) - 3  # header, divider, footer

    def _event_loop(self):
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
            row_num = f"{{:{self.left_gutter - 1}d}}".format(row + 1)
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
        y = self._table_height() + 1
        t = self._term
        w = t.width
        num = len(self._nb_items)
        msg = f"Rows {self._start + 1} - {self._end} out of {num}"
        msg += " | Move with arrow Up/Down and PgUp/PgDn"
        rpad = " " * (t.width - len(msg))
        print(f"{t.move_xy(0, y)}{self.c_div}{msg}{rpad}{self.c_norm}")

    def _show_details(self):
        nb = self._nb_items[self._cur]
        t, y = self._term, self._table_height() + 2
        height = t.height - y - 1

        # Print Path at top
        path = Path(nb.path).name[: t.width]
        prn(f"{t.move_xy(0, y)}Path: {self.c_dim}{path}{self.c_norm}")
        y += 1

        # Print description lines
        lines = nb.desc_lines[:height]
        for i, line in enumerate(lines):
            s = line[: t.width - 1].rstrip()
            prn(f"{t.move_xy(0, y + i)}{s}")

    def _show_footer(self):
        t = self._term
        prn(f"{t.move_xy(0, t.height)}{self.c_ftr}Press 'Enter' to run, 'q' to Quit")

    def _process_input(self):
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
        t = self._term

        # Title of dialog box is notebook name
        title = nb.name

        # Build menu of notebook run options and corresponding paths
        if Ext.SOL.value in nb.types:
            options = (("s", "Solution"), ("", "Exercise"))
        else:
            options = (("", "User"),)

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
                f"{t.move_xy(x, y + i)}{self.c_box_optc}{keypress}{self.c_norm} Run {self.c_box_optc}{name}{self.c_norm} Notebook"
            )

        _flush()

        # Read input
        with t.cbreak():
            nb_choice = None
            while nb_choice is None:
                val = t.inkey(timeout=60)
                if val:
                    if val.code == t.KEY_ESCAPE:
                        nb_choice = ""
                        break
                    for c, name in options:
                        if (c == "" and val.code == t.KEY_ENTER) or (
                            not val.is_sequence and val.lower() == c
                        ):
                            nb_choice = name
                            break
        if not nb_choice:
            return  # whatevs!

        jp = Jupyter()
        path_ext = {
            "User": Ext.USER.value,
            "Solution": Ext.SOL.value,
            "Exercise": Ext.EX.value,
        }[nb_choice]
        p = Path(nb.path)
        print(f"PARTS={p.parts}")
        #jp.open(nb.path)
        time.sleep(5)

#
#     primary_bg = "#2092ed"
#
#     sbar_kwargs = dict(
#         sbar_trough_color=PySG.theme_background_color(),
#         sbar_background_color="lightgrey",
#         sbar_frame_color="grey",
#         sbar_arrow_color="grey",
#     )
#     description_widget = PySG.Multiline(
#         expand_y=True,
#         expand_x=True,
#         write_only=True,
#         background_color="white",
#         key="Description",
#         font=get_font(11),
#         **sbar_kwargs,
#     )
#     description_frame = PySG.Frame(
#         "Description", layout=[[description_widget]], expand_y=True, expand_x=True
#     )
#
#     columns = [0, 0, 0]
#     for row in nb_table:
#         for col_index in range(2):
#             w = len(row[col_index]) // 2
#             if columns[col_index] < w:
#                 columns[col_index] = w
#         w = len(row[2])
#         if columns[2] < w:
#             columns[2] = w
#
#     header_row = ["Type" + " " * 40, "Location" + " " * 80, "Title" + " " * 160]
#     sort_order = list(Notebooks.DEFAULT_SORT_KEYS)
#     sort_dir = [1] * len(sort_order)
#     nb_table_widget = PySG.Table(
#         key="Table",
#         values=nb_table,
#         # without added spaces, the headings will be centered instead of left-aligned
#         headings=header_row,
#         expand_x=True,
#         expand_y=False,
#         justification="left",
#         enable_click_events=True,
#         enable_events=True,
#         alternating_row_color="#def",
#         col_widths=columns,
#         auto_size_columns=False,
#         selected_row_colors=("white", primary_bg),
#         header_text_color="black",
#         header_font=get_font(11, style="bold"),
#         font=get_font(11),
#         header_relief=PySG.RELIEF_FLAT,
#         header_background_color="#eee",
#     )
#
#     open_buttons = {}
#     for ext in Ext.USER, Ext.SOL, Ext.EX:
#         if ext == Ext.USER:
#             label = "Open Example"
#         elif ext == Ext.SOL:
#             label = "Open Solution"
#         else:
#             label = "Open Exercise"
#         open_buttons[ext] = PySG.Button(
#             label,
#             tooltip=f"Open selected notebook",
#             button_color=("white", primary_bg),
#             disabled_button_color=("#696969", "#EEEEEE"),
#             border_width=0,
#             # auto_size_button=True,
#             size=len(label),
#             key=f"open+{ext.value}",
#             disabled=True,
#             pad=(20, 20),
#             use_ttk_buttons=True,
#             font=get_font(11),
#         )
#
#     quit_button = PySG.Button(
#         "Quit",
#         tooltip="Quit the application",
#         button_color=("white", primary_bg),
#         border_width=0,
#         key="quit",
#         disabled=False,
#         pad=(10, 10),
#         auto_size_button=False,
#         use_ttk_buttons=True,
#         font=get_font(11),
#     )
#
#     intro_nb, flowsheet_nb = "intro", "flowsheet"
#     start_notebook_paths = {}
#     for key in notebooks.keys():
#         sect, name, ext = key
#         # print(key)
#         if sect[0] == "docs" and sect[1] == "tut":
#             if name == "introduction" and ext == Ext.USER.value:
#                 start_notebook_paths[intro_nb] = notebooks[key].path
#             elif name == "hda_flowsheet" and ext == Ext.SOL.value:
#                 start_notebook_paths[flowsheet_nb] = notebooks[key].path
#
#     # Find the start-here notebooks and add buttons for them
#     start_here_panel = []
#     # Be robust to not-found notebooks
#     if len(start_notebook_paths) == 0:
#         _log.warning("Could not find 'Start here' notebooks")
#     else:
#         start_here_panel.append(PySG.Text("Not sure where to start? Try one of these:"))
#         sh_kwargs = dict(
#             text_color=primary_bg,
#             font=get_font(11, style="underline"),
#             enable_events=True,
#         )
#         for sh_nb, text in ((intro_nb, "Introduction"), (flowsheet_nb, "Flowsheet")):
#             if sh_nb in start_notebook_paths:
#                 button = PySG.Text(text, key=f"starthere_{sh_nb}", **sh_kwargs)
#                 start_here_panel.append(button)
#                 if text == "Introduction":
#                     start_here_panel.append(PySG.Text("for an IDAES overview or"))
#                 else:
#                     start_here_panel.append(PySG.Text("for a flowsheet tutorial"))
#
#     instructions = PySG.Text(
#         "Select a notebook and then select 'Open' to open it in Jupyter"
#     )
#     full_path = PySG.Text("Path:")
#
#     layout = [
#         [instructions],
#         [nb_table_widget],
#         [full_path],
#         [description_frame],
#         [
#             PySG.Text("Actions:"),
#             open_buttons[Ext.USER],
#             open_buttons[Ext.EX],
#             open_buttons[Ext.SOL],
#             PySG.P(),
#             quit_button,
#         ],
#     ]
#
#     if start_here_panel:
#         layout.insert(0, [PySG.VerticalSeparator(pad=(0, 20)), start_here_panel])
#
#     # create main window
#     w, h = PySG.Window.get_screen_size()
#     capped_w = min(w, 3840)
#     width = int(capped_w // 1.4)
#     height = int(min(h - 10, width // 2))
#
#     window = PySG.Window(
#         "IDAES Notebook Browser",
#         layout,
#         size=(width, height),
#         finalize=True,
#         icon=IDAES_ICON_B64,
#         font=get_font(11),
#         text_justification="left",
#         resizable=True,
#     )
#
#     nbdesc = NotebookDescription(notebooks, window["Description"].Widget)
#     # Event Loop to process "events" and get the "values" of the inputs
#     jupyter = Jupyter(lab=use_lab)
#     shown = None
#     try:
#         while True:
#             _log.debug("Wait for event")
#             event, values = window.read()
#             _log.debug("Event detected")
#             # if user closes window or clicks cancel
#             if event == PySG.WIN_CLOSED or event == "quit":
#                 break
#             #print(f"@@event: {event} ; values: {values}")
#             if isinstance(event, int):
#                 _log.debug(f"Unhandled event: {event}")
#             elif isinstance(event, str):
#                 if event == "Table":
#                     try:
#                         row_index = values[event][0]
#                         shown = preview_notebook(
#                             nb_table, nb_table_meta, nbdesc, open_buttons, row_index
#                         )
#                         path = nbdesc.get_path(*shown)
#                         full_path.update(f"Path: {path}")
#                     except IndexError:
#                         pass
#                 elif event.startswith("open+"):
#                     if shown:
#                         path = nbdesc.get_path(*shown)
#                         jupyter.open(path)
#                 elif event.startswith("starthere"):
#                     what = event.split("_")[-1]
#                     path = start_notebook_paths[what]
#                     print(path)
#                     jupyter.open(path)
#             # event=('Table', '+CLICKED+', (-1, 0)) ; values: {'Table': [5]}
#             elif isinstance(event, tuple) and event[0] == "Table":
#                 try:
#                     row, col = event[2]
#                     if row == -1:
#                         # TODO: sort
#                         pass
#                 except (ValueError, IndexError):
#                     pass
#     except KeyboardInterrupt:
#         print("Stopped by user")
#
#     if stop_notebooks_on_quit:
#         print("** Stop running notebooks")
#         try:
#             jupyter.stop()
#         except KeyboardInterrupt:
#             pass
#     _log.info("Close main window")
#     window.close()
#     _log.info(f"end:run-gui")
#     return 0
#
#
# def preview_notebook(nb_table, nb_table_meta, nbdesc, open_buttons, row_index) -> bool:
#     data_row = nb_table[row_index]
#     meta_row = nb_table_meta[row_index]
#     section = data_row[1]
#     name = meta_row[1]
#     type_ = Ext.USER.value
#     nbdesc.show(section, name, type_)
#     shown = (section, name, meta_row[0])
#     is_tut = meta_row[2]
#     open_buttons[Ext.USER].update(disabled=is_tut)
#     open_buttons[Ext.EX].update(disabled=not is_tut)
#     open_buttons[Ext.SOL].update(disabled=not is_tut)
#     return shown
#
#
