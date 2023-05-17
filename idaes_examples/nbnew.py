"""
User interface for creating a new notebook
"""
from pathlib import Path
import sys
from typing import Union, Tuple, Iterator

from blessed import Terminal
import nbformat as nbf
import yaml

from idaes_examples.util import read_toc, find_notebook_root, src_suffix_len


ABORT = 255  # return code


class Colors:
    def __init__(self, term):
        self.reg, self.title, self.em, self.light, self.err, self.rev = (
            term.white_on_black,
            term.green,
            term.orange,
            term.steelblue,
            term.red,
            term.black_on_green,
        )


def press_any_key(term):
    col = Colors(term)
    print(f"{col.reg}Press any key to continue...")
    with term.cbreak():
        term.inkey()


def ask_yesno(t: Terminal, q: str, default=None) -> bool:
    if default is True:
        yes_char, no_char = "Y", "n"
    elif default is False:
        yes_char, no_char = "y", "N"
    else:
        yes_char, no_char = "y", "n"
    print(f"{q} [{yes_char}/{no_char}]? ", end="", flush=True)

    affirmed = None
    with t.cbreak():
        while True:
            yn = t.inkey().lower()
            if yn == "y":
                affirmed = True
                break
            elif yn == "n":
                affirmed = False
                break
            elif ord(yn) == 13 and default is not None:
                affirmed = default
                break

    return affirmed


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

        spc = " " * 10
        self._hdr = f"{self.colors.rev}{spc}add notebook{spc}{self.colors.reg}"

    def run(self) -> Union[Path, None]:
        """Run the UI.

        Returns:
            Path to added notebook, None if none was added.
        """
        t, c = self.term, self.colors
        dirs = self._get_notebook_dirs()
        result = None

        with t.location():
            done = False
            while not done:
                selected = ""
                print(t.home + t.on_black + t.clear, end="")
                print(self._hdr)
                print(f"{c.title}Select an existing directory{c.reg}")
                dm = self._dir_menu(dirs)
                print(f"{c.title}>{c.reg} ", end="", flush=True)

                selected = self._select_dir(dm)

                filename = self._pick_notebook_name(selected)
                done = filename is not None

            section_path = selected[1]
            notebook_path = section_path / filename
            if self._create_notebook(notebook_path):
                notebook_doc = notebook_path.stem[:-src_suffix_len] + "_doc"
                new_toc = self._add_notebook_to_config(str(selected[0]), notebook_doc)
                # write modified TOC
                if new_toc is not None:
                    self._write_new_toc(new_toc)
                    result = notebook_path  # success!
                else:
                    print(f"{c.err}Failed to add notebook to config{c.reg}")
                    press_any_key(t)

        return result

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

    def _dir_menu(self, dirs: Iterator[Tuple[Path, Path]]) -> dict[str, Tuple[Path, Path]]:
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
        print(f"{c.reg}Add new notebook in {c.light}{rel_path}{c.reg}")

        affirmed, nb_name = False, ""
        while not affirmed:
            print(f"Type notebook name (without {c.light}_src.ipynb{c.reg} suffix)")
            print(f"(press {c.em}<Enter>{c.reg} to return to previous menu)")
            name = input(f"{c.em}> {c.reg}")
            if not name:
                affirmed, nb_name = True, None
                continue
            nb_name = f"{name}_src.ipynb"
            if (full_path / nb_name).exists():
                print(f"{c.err}File exists!{c.reg} Operation canceled.")
                press_any_key(t)
                continue
            affirmed = ask_yesno(t, f"Create {c.light}{nb_name}{c.reg}\nin "
                                    f"{c.light}{full_path}{c.reg}", default=False)
            if not affirmed:
                print("\nOperation canceled.")
        print()

        return nb_name

    def _create_notebook(self, path: Path) -> bool:
        t, c = self.term, self.colors

        result = False
        print(f"{c.reg}Create notebook at: {c.light}{path}{c.reg}")

        notebook = nbf.v4.new_notebook()
        try:
            with path.open("w", encoding="utf-8") as f:
                nbf.write(notebook, f)
            result = True
        except IOError as err:
            print(f"{c.err}Failed to write new notebook: {err}{c.reg}")

        press_any_key(t)
        return result

    def _add_notebook_to_config(self, dirname: str, path: str) -> Union[dict, None]:
        entry = {"file": (Path(dirname) / path).as_posix()}
        dirname = Path(dirname).as_posix()
        print(f"Add notebook to section {dirname}: {path}")
        toc = read_toc(self.root / "notebooks")
        found = False
        for part in toc["parts"]:
            for chapter in part["chapters"]:
                for item in chapter:
                    # Chapter with sections
                    if "sections" in item:
                        for section in chapter["sections"]:
                            if section.get("file", "").startswith(dirname):
                                chapter["sections"].append(entry)
                                found = True
                                break
                    # Chapter w/o sections
                    elif isinstance(item, dict) and item.get("file", "").startswith(
                        dirname
                    ):
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
        path = AddNotebook(self.term).run()

        if path is None:
            return ABORT

        print("All done! You can now edit your new notebook at:")
        print(path)

        return 0

# For running standalone -- but usually invoked through `idaesx new`


def main():
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
