import pdb

from pathlib import Path
import sys
from typing import Union, Tuple, Iterator

from blessed import Terminal
import nbformat as nbf
import yaml

from idaes_examples.util import read_toc, find_notebook_root, src_suffix_len


class Colors:
    def __init__(self, term):
        self.reg, self.title, self.em, self.light, self.err = (
            term.white,
            term.green,
            term.orange,
            term.steelblue,
            term.red,
        )


def press_any_key(term):
    col = Colors(term)
    print(f"{col.reg}Press any key to continue...")
    with term.cbreak():
        term.inkey()


def multiple_choice(term: Terminal, options: dict[str, str]) -> str:
    with term.location():
        col = Colors(term)
        print(term.home + term.on_black + term.clear, end="")
        mc_opt = mc_show(term, options)
        x, y = 2, len(mc_opt) + 1
        min_val, max_val = 1, len(mc_opt) + 1
        with term.cbreak():
            val_num = -1
            while not (min_val <= val_num <= max_val):
                if val_num != -1:
                    print(
                        (
                            f"{term.move_xy(10, y)}{col.err}"
                            f"Select a number from {min_val} to {max_val}"
                            f"{term.normal}{term.move_xy(x, y)}"
                        ),
                        end="",
                        flush=True,
                    )
                val = term.inkey()
                if val.lower() == "q":
                    return ""
                try:
                    val_num = int(val)
                except ValueError:
                    val_num = -2
    return mc_opt[val_num - 1]


def mc_show(term: Terminal, options: dict[str, str]) -> list[str]:
    choices = []
    col = Colors(term)
    print(f"{col.title}Select an action")
    for i, (name, text) in enumerate(options.items()):
        print(f"  {col.em}{i + 1}{col.reg} {name} - {col.light}{text}")
        choices.append(name)
    print()
    print(f"  {col.em}q{col.reg} quit - {col.light}quit program")
    print()
    print(f"{col.title}>{col.reg} ", end="", flush=True)

    return choices


def add_notebook(term: Terminal, curdir=None) -> Union[Path, None]:
    if curdir is None:
        cwd = Path.cwd()
    else:
        cwd = Path(curdir)
    root = find_notebook_root(cwd)
    dirs = get_notebook_dirs(root / "notebooks")
    press_any_key(term)
    col = Colors(term)
    result = None
    with term.location():
        done = False
        while not done:
            selected = ""
            print(term.home + term.on_black + term.clear, end="")
            print(f"{col.title}Select an existing directory{col.reg}")
            print(f"{col.light}Type '{col.em}q{col.light}' to return to previous menu")
            dm = sd_show(term, dirs)
            print(f"{col.title}>{col.reg} ", end="", flush=True)
            with term.cbreak():
                selected = ""
                while selected == "":
                    val = term.inkey()
                    if val == "q":
                        selected = "q"
                    elif val in dm:
                        print(f"{col.em}{val}{col.reg}")
                        selected = dm[val]
            if selected == "q":
                filename = "~"
                done = True
            else:
                filename = pick_notebook_name(term, selected)
                done = filename is not None
        if filename != "~":
            notebook_path = selected[1] / filename
            if create_notebook(term, notebook_path):
                notebook_doc = notebook_path.stem[:-src_suffix_len] + "_doc"
                new_toc = add_notebook_to_config(root, str(selected[0]), notebook_doc)
                if new_toc is not None:
                    print("New TOC:")
                    yaml.dump(new_toc, stream=sys.stdout, indent=2)
                    result = notebook_path
                else:
                    print(f"{col.err}Failed to add notebook to config{col.reg}")
                    press_any_key(term)
    return result


def create_notebook(term: Terminal, path: Path) -> bool:
    col = Colors(term)
    result = False
    print(f"{col.reg}Create notebook at: {col.light}{path}{col.reg}")
    notebook = nbf.v4.new_notebook()
    try:
        with path.open("w", encoding="utf-8") as f:
            nbf.write(notebook, f)
        result = True
    except IOError as err:
        print(f"{col.err}Failed to write new notebook: {err}{col.reg}")
    press_any_key(term)
    return result


def add_notebook_to_config(root: Path, dirname: str, path: str) -> bool:
    entry = {"file": (Path(dirname) / path).as_posix()}
    dirname = Path(dirname).as_posix()
    print(f"Add notebook to section {dirname}: {path}")
    toc = read_toc(root / "notebooks")
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


def pick_notebook_name(term: Terminal, selected: Tuple[Path, Path]) -> Union[str, None]:
    col = Colors(term)
    rel_path, full_path = selected
    name = None
    print(f"{col.reg}Add new notebook in {col.light}{rel_path}{col.reg}")
    affirmed, nb_name = False, ""
    while not affirmed:
        print(f"Type notebook name (without {col.light}_src.ipynb{col.reg} suffix)")
        print(f"(press {col.em}<Enter>{col.reg} to return to previous menu)")
        name = input(f"{col.em}> {col.reg}")
        if not name:
            affirmed, nb_name = True, None
            continue
        nb_name = f"{name}_src.ipynb"
        if (selected[1] / nb_name).exists():
            print(f"{col.err}File exists!{col.reg} Operation canceled.")
            press_any_key(term)
            continue
        print(
            (
                f"Create {col.light}{nb_name}{col.reg}\nin directory "
                f"{col.light}{full_path}{col.reg} [y/n]? "
            ),
            end="",
            flush=True,
        )
        with term.cbreak():
            while True:
                yn = term.inkey().lower()
                if yn == "y":
                    affirmed = True
                    break
                elif yn == "n":
                    affirmed = False
                    break
        if affirmed:
            print()
        else:
            print("\nOperation canceled.")
    return nb_name


def sd_show(term, dirs: Iterator[Tuple[Path, Path]]) -> dict[str, Tuple[Path, Path]]:
    letters = "abcdefghijklmnoprstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    dirs = list(dirs)
    if len(dirs) > len(letters):
        raise RuntimeError(f"Too many directories ({len(dirs)})!")
    col = Colors(term)
    dir_map = {}
    for i, (d, p) in enumerate(dirs):
        ltr = letters[i]
        print(f"{col.em}{ltr}{col.reg} {d}")
        dir_map[ltr] = (d, p)
    return dir_map


def get_notebook_dirs(path) -> Iterator[Tuple[Path, Path]]:
    toc = read_toc(path)
    toc_files = set()
    for part in toc["parts"]:
        for chapter in part["chapters"]:
            for item in chapter:
                if "sections" in item:
                    for section in chapter["sections"]:
                        if "file" in section:
                            toc_files.add(Path(section["file"]).parent)
                elif isinstance(item, dict) and "file" in item:
                    print(f"@@ {item['file']}")
                    toc_files.add(Path(item["file"]).parent)
    return sorted(((p, path / p) for p in toc_files))


class App:
    def __init__(self, term):
        self.term = term

    def run(self):
        while True:  # allow return to top menu
            choice = multiple_choice(
                self.term, {"new": "start new notebook", "unhold": "move held notebook"}
            )
            if not choice:
                print("Abort")
                return 1

            method = getattr(self, f"do_{choice}")
            retcode = method()
            if retcode <= 0:
                break

    def do_new(self):
        path = add_notebook(self.term)
        if path is None:
            return 1
        print(path)
        return 0

    def do_unhold(self):
        return 0


def main():
    term = Terminal()
    app = App(term)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
