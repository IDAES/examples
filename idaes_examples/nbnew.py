"""
User interface for creating a new notebook
"""
from enum import Enum
from pathlib import Path
import subprocess
import sys
from typing import Union, Tuple, Iterator, List

from blessed import Terminal
import nbformat as nbf
import yaml

from idaes_examples.util import (
    read_toc,
    find_notebook_root,
    Ext,
    change_notebook_ext,
)

ABORT = 255  # return code for abort
RETRY = 254  # return code for try again


class Colors:
    def __init__(self, term):
        self.reg, self.title, self.em, self.light, self.err, self.rev, self.prompt = (
            term.white_on_black,
            term.green,
            term.orange,
            term.steelblue,
            term.red,
            term.black_on_steelblue,
            term.green,
        )
        self.star = f"\u2728"
        self.question = f"\u2754"


def press_any_key(term):
    c = Colors(term)
    msg = f"{c.reg}Press any key to continue..."
    n = term.length(msg)
    y, x = term.get_location()
    with term.location(x, y):
        print(msg, end="", flush=True)
        with term.cbreak():
            term.inkey()
    with term.location(x, y):
        print(" " * n, end="", flush=True)


def ask_yesno(t: Terminal, q: str, default=None) -> bool:
    c = Colors(t)
    if default is True:
        yes_char, no_char = "Y", "n"
    elif default is False:
        yes_char, no_char = "y", "N"
    else:
        yes_char, no_char = "y", "n"
    print(f"{c.question}{q} [{yes_char}/{no_char}]? ", end="", flush=True)

    affirmed = None
    with t.cbreak():
        while True:
            yn = t.inkey().lower()
            if yn == "y":
                affirmed = True
                print(f"{c.em}yes", end="")
                break
            elif yn == "n":
                print(f"{c.em}no", end="")
                affirmed = False
                break
            elif ord(yn) == 13 and default is not None:
                affirmed = default
                print(f"{c.em}yes" if default else f"{c.em}no", end="")
                break
    print(f"{c.reg}")
    return affirmed


class NotebookType(Enum):
    reg = "regular"
    tut = "tutorial"


class AddNotebook:
    """Terminal-based UI for adding a new notebook to one of the existing
    directories in the table of contents.
    """

    def __init__(self, term: Terminal, path: Path = None):
        """Constructor.

        Args:
            term: blessed.Terminal instance
            path: Starting directory
        """
        self.term = term
        self.colors = Colors(term)
        if path is None:
            self.cwd = Path.cwd()
        else:
            self.cwd = Path(path)
        self.root = find_notebook_root(self.cwd)
        self.notebook_dir = self.root / "notebooks"

        c, spc = self.colors, " " * 10
        self._hdr = f"{c.rev}{spc}add notebook{spc}{c.reg}"
        self._git = "git"

    @property
    def git_program(self):
        return self._git

    @git_program.setter
    def git_program(self, value):
        self._git = value

    def run(self) -> Union[Path, None]:
        """Run the UI.

        Returns:
            Path to added notebook, None if none was added.
        """
        t, c = self.term, self.colors
        dirs = self._get_notebook_dirs()
        result = None

        run_done = False
        while not run_done:
            with t.location():
                done = False
                while not done:
                    selected = ""
                    print(t.home + t.on_black + t.clear, end="")
                    print(self._hdr)
                    print(f"{c.title}Select an existing directory{c.reg}")
                    dm = self._dir_menu(dirs)
                    print(f"{c.prompt}>{c.reg} ", end="", flush=True)

                    selected = self._select_dir(dm)

                    filename = self._pick_notebook_name(selected)
                    done = filename is not None

                section_path = selected[1]
                notebook_path = section_path / filename
                notebook_type = self._get_notebook_type()
                if self._create_notebook(notebook_path, notebook_type):
                    notebook_doc = notebook_path.stem + "_doc"
                    new_toc = self._add_notebook_to_config(
                        str(selected[0]), notebook_doc
                    )
                    # write modified TOC
                    if new_toc is not None:
                        self._write_new_toc(new_toc)
                        result = notebook_path  # success!
                        run_done = True
                    else:
                        print(f"Did {c.err}not{c.reg} change JupyterBook configuration")
                        press_any_key(t)

        return result

    def rpath(self, p: Path, to_root: bool = False, as_dir: bool = False) -> str:
        """Get POSIX-style path relative to notebook directory or root."""
        if to_root:
            rel = p.relative_to(self.root)
        else:
            rel = p.relative_to(self.notebook_dir)
        if as_dir and not p.is_dir():
            return rel.parent.as_posix()
        return rel.as_posix()

    # ---
    # Helper methods for run(), in order called
    # ---

    def _get_notebook_dirs(self) -> Iterator[Tuple[Path, Path]]:
        toc_dir = self.notebook_dir
        toc = read_toc(toc_dir)
        toc_files = set()
        for part in toc["parts"]:
            for chapter in part["chapters"]:
                if "sections" in chapter:
                    for section in chapter["sections"]:
                        if "file" in section:
                            toc_files.add(Path(section["file"]).parent)
                elif "file" in chapter:
                    toc_files.add(Path(chapter["file"]).parent)
        return sorted(((p, toc_dir / p) for p in toc_files))

    def _dir_menu(
        self, dirs: Iterator[Tuple[Path, Path]]
    ) -> dict[str, Tuple[Path, Path]]:
        letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        c = self.colors
        dirs = list(dirs)
        if len(dirs) > len(letters):
            raise RuntimeError(f"Too many directories ({len(dirs)} > 52)!")
        dir_map = {}
        for i, (d, p) in enumerate(dirs):
            ltr = letters[i]
            print(f"{c.em}{ltr}{c.reg} {d}")
            dir_map[ltr] = (d, p)
        return dir_map

    def _select_dir(self, menu: dict[str, Tuple[Path, Path]]) -> Tuple[Path, Path]:
        t, c = self.term, self.colors
        with t.cbreak():
            selected = ""
            while selected == "":
                val = t.inkey()
                if val in menu:
                    print(f"{c.em}{val}{c.reg}")
                    selected = menu[val]
        return selected

    def _pick_notebook_name(self, selected: Tuple[Path, Path]) -> Union[str, None]:
        t, c = self.term, self.colors

        rel_path, full_path = selected
        print(f"{c.star}Add new notebook in {c.light}{rel_path}{c.reg}")

        affirmed, nb_name = False, ""
        while not affirmed:
            print(f"Type notebook name (without {c.light}.ipynb{c.reg} suffix)")
            print(f"(press {c.em}<Enter>{c.reg} to return to previous menu)")
            name = input(f"{c.prompt}> {c.reg}")
            if not name:
                affirmed, nb_name = True, None
                continue
            nb_name = f"{name}.ipynb"
            if (full_path / nb_name).exists():
                print(f"{c.err}File exists!{c.reg} Operation canceled.")
                press_any_key(t)
                continue
            rel_path = self.rpath(full_path)
            affirmed = ask_yesno(
                t,
                f"Create {c.light}{nb_name}{c.reg} in {c.light}{rel_path}{c.reg}",
                default=False,
            )
            if not affirmed:
                print("Operation canceled.")

        return nb_name

    def _get_notebook_type(self) -> NotebookType:
        r = ask_yesno(self.term, "Will this notebook be a tutorial")
        return NotebookType.tut if r else NotebookType.reg

    def _create_notebook(self, path: Path, nb_type: NotebookType) -> bool:
        t, c = self.term, self.colors

        result = False
        tut_str = "tutorial " if nb_type is NotebookType.tut else ""
        print(f"{c.star}Create {tut_str}notebook")

        # Create source [ext=None] and all derived notebooks
        ext = [None, Ext.DOC, Ext.TEST, Ext.USER]
        if nb_type is NotebookType.tut:
            ext.extend([Ext.EX, Ext.SOL])

        created, result = [], True
        for e in ext:
            if e is None:
                p = path
            else:
                p = change_notebook_ext(path, e.value)
            notebook = nbf.v4.new_notebook()
            try:
                with p.open("w", encoding="utf-8") as f:
                    nbf.write(notebook, f)
                created.append(p)
            except IOError as err:
                print(f"{c.err}Failed to write new notebook: {err}{c.reg}")
                result = False
                break

        if result:
            commit_ok = self._git_commit(created)
            if not commit_ok:
                result = False

        if result:
            print(
                f"Created {len(created)} notebooks in "
                f"{c.light}{self.rpath(path, as_dir=True)}{c.reg}:"
            )
            for p in created:
                print(f"  {c.light}{p.name}{c.reg}")
        else:
            for p in created:
                try:
                    p.unlink()
                except IOError:
                    print(f"{c.err}Failed to clean up notebook: {p}")

        press_any_key(t)
        return result

    def _git_commit(self, created: List[Path]) -> bool:
        assert len(created) > 0

        t, c = self.term, self.colors
        print(f"{c.star}Add and commit files to git")

        ok = False

        cwd = Path.cwd().absolute()
        file_list = [str(p.relative_to(cwd)) for p in created]
        command = [self.git_program, "add"] + file_list
        try:
            print(f"  Run command: {c.light}{' '.join(command)}{c.reg}")
            proc = subprocess.run(command, capture_output=True, check=True)
        except subprocess.CalledProcessError as err:
            print(f"Command {c.light}{' '.join(command)}{c.reg} failed: {err}")
            print(f"{c.err}Could not stage files in git{c.reg}")
        else:
            nb_name = created[0].stem[:-4]
            nb_loc = self.rpath(created[0].parent)
            command = [
                self.git_program,
                "commit",
                "-m",
                f"New notebook {nb_name} in directory {nb_loc}",
            ]
            print(f"  Run command: {c.light}{' '.join(command)}{c.reg}")
            try:
                proc = subprocess.run(command, capture_output=True, check=True)
            except subprocess.CalledProcessError as err:
                print(f"Command {c.light}{' '.join(command)}{c.reg} failed ({err})")
                print(f"{c.err}Could not commit staged files in git{c.reg}")
            else:
                ok = True
                print(f"Added {len(created)} files")

        return ok

    def _add_notebook_to_config(self, dirname: str, path: str) -> Union[dict, None]:
        c = self.colors
        print(f"{c.star}Update JupyterBook configuration")

        entry = {"file": (Path(dirname) / path).as_posix()}
        dirname = Path(dirname).as_posix()
        print(
            f"Add {c.light}{path}{c.reg} notebook to section {c.light}{dirname}{c.reg}"
        )
        toc = read_toc(self.root / "notebooks")
        found = False
        for part in toc["parts"]:
            for chapter in part["chapters"]:
                for item in chapter:
                    # Chapter with sections
                    if "sections" in item:
                        for section in chapter["sections"]:
                            if section.get("file", "").startswith(dirname):
                                if entry in chapter["sections"]:
                                    part_name = part.get("caption", "?")
                                    chap_name = chapter.get("file", "?")
                                    print(
                                        f"{c.err}Found existing entry in "
                                        f"{c.light}_toc.yml{c.err} at{c.light}"
                                        f"({part_name}).chapters.({chap_name})"
                                        f"{c.err}!{c.reg}"
                                    )
                                    break
                                chapter["sections"].append(entry)
                                found = True
                                break
                    # Chapter w/o sections
                    elif isinstance(item, dict) and item.get("file", "").startswith(
                        dirname
                    ):
                        if entry in part["chapters"]:
                            part_name = part.get("caption", "?")
                            print(
                                f"{c.err}Found existing entry in {c.reg}"
                                f"({part_name}).chapters{c.err}!{c.reg}"
                            )
                            break
                        part["chapters"].append(entry)
                        found = True
                    if found:
                        return toc
        return None

    def _write_new_toc(self, d: dict):
        """Preserve comments from original YAML.
        Assumes that new file differs only by adding lines to original.
        """
        nl = "\n"
        lines_out = yaml.dump(d, indent=2).split(nl)
        toc_path = self.notebook_dir / "_toc.yml"

        with toc_path.open("r", encoding="utf-8") as f:
            lines_in = f.read().split(nl)

        result = []
        i = 0
        for line_in in lines_in:
            s_in = line_in.strip()
            if s_in and s_in[0] == "#":
                result.append(line_in)
            else:
                while i < len(lines_out) and lines_out[i].strip() != s_in:
                    result.append(lines_out[i])
                    i += 1
                if i < len(lines_out):
                    result.append(lines_out[i])
                    i += 1

        with toc_path.open("w", encoding="utf-8") as f:
            for line in result:
                f.write(line + nl)


class App:
    def __init__(self):
        self.term = Terminal()

    def run(self) -> int:
        try:
            retcode = self.do_new()
        except KeyboardInterrupt:
            retcode = ABORT

        if retcode == ABORT:
            c = Colors(self.term)
            print(f"{c.err}Abort{c.reg}")

        return retcode

    def do_new(self) -> int:
        adder = AddNotebook(self.term)
        path = adder.run()

        if path is None:
            return ABORT

        # Print success. Use some whitespace to clear out any cruft
        # left on the screen from previous output of the terminal tool.
        c = Colors(self.term)
        print("Success! You can now edit your new notebook at:")
        print(" " * 60)
        print(f"{c.em}{adder.rpath(path)}{c.reg}{' ' * 40}")
        print()

        return 0


# For running standalone -- but usually invoked through `idaesx new`


def main():
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
