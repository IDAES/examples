"""
Build the examples
"""
import argparse
import json
import logging
import os
from pathlib import Path
import re
from subprocess import check_call
import sys
import time
import traceback
import webbrowser
import yaml

# package
from idaes_examples.util import (
    add_vb,
    process_vb,
    add_vb_flags,
    find_notebook_root,
    NB_ROOT,
    NB_CACHE,
    NB_CELLS,
    NB_META,
    NB_IDAES,
    NB_SKIP,
    read_toc,
    find_notebooks,
    src_suffix,
    src_suffix_len,
    Ext,
    ExtAll,
    Tags,
)
from idaes_examples.util import _log as util_log

# third-party
from jupyter_cache import get_cache
import nbformat as nbf


# -------------
#   Logging
# -------------

_log = logging.getLogger(__name__)
_h = logging.StreamHandler()
_h.setFormatter(
    logging.Formatter("[%(levelname)s] %(asctime)s %(module)s - %(message)s")
)
_log.addHandler(_h)

# -------------
#  Preprocess
# -------------

DEV_DIR = "_dev"  # special directory to include in preprocessing


def preprocess(srcdir=None, dev=False) -> int:
    """Preprocess Jupyter notebooks.

    Returns:
        Number of notebooks considered for preprocessing.
    """
    src_path = find_notebook_root(Path(srcdir))
    src_path /= NB_ROOT
    if dev:
        src_path /= "_dev"
        src_path /= NB_ROOT
    toc = read_toc(src_path)
    t0 = time.time()
    results = find_notebooks(src_path, toc, _preprocess)
    for dev_file in (src_path / DEV_DIR).glob(f"*{src_suffix}.ipynb"):
        _preprocess(dev_file)
    dur = time.time() - t0
    n = len(results)
    n_processed = sum(results.values())
    n_skipped = n - n_processed
    _log.info(
        f"Preprocessed {n} notebooks (changed {n_processed} / "
        f"skipped {n_skipped}) in {dur:.1f} seconds"
    )
    Commands.subheading(f"did {n_processed}, skipped {n_skipped}")
    return n


# Which tags to exclude for which generated file
exclude_tags = {
    Ext.TEST.value: {Tags.EX.value, Tags.NOAUTO.value},
    Ext.EX.value: {Tags.TEST.value, Tags.SOL.value, Tags.AUTO.value},
    Ext.SOL.value: {Tags.TEST.value, Tags.AUTO.value},
    Ext.DOC.value: {Tags.EX.value, Tags.TEST.value, Tags.NOAUTO.value},
    Ext.USER.value: {Tags.TEST.value, Tags.AUTO.value},  # same as _solution
}

# notebook filenames, e.g. in markdown links
# NOTE: assume no spaces in filenames
nb_file_pat = re.compile(f"([a-zA-Z0-9_\\-:.+]+){src_suffix}\\.ipynb")
nb_file_subs = {e.value: f"\\1_{e.value}.ipynb" for e in Ext if e != Ext.DOC}
# For MyST, replace .ipynb with .md in the 'doc' notebook's link
nb_file_subs[Ext.DOC.value] = f"\\1_{Ext.DOC.value}.md"


def _preprocess(nb_path: Path, **kwargs) -> bool:
    _log.info(f"File: {nb_path}")

    def ext_path(p: Path, ext: Ext = None, name: str = None) -> Path:
        """Return new path with extension changed."""
        name, base = name or ext.value, p.stem[:-src_suffix_len]
        p_new = p.parent / f"{base}_{name}.ipynb"
        _log.debug(f"Path[{name}] = '{p_new}'")
        return p_new

    def update_changed(nb_path: Path, ext: Ext, mtime: float, d: dict):
        p = ext_path(nb_path, ext=ext)
        if not p.exists():
            d["exists"].add(ext.value)
        elif p.stat().st_mtime <= mtime:
            d["mtime"].add(ext.value)

    t0 = time.time()

    # Check whether source was changed after the derived notebooks.
    # Only consider types of derived notebooks that are always generated.
    src_mtime, changed = nb_path.stat().st_mtime, False
    changed_because = {"exists": set(), "mtime": set()}
    for ext in (Ext.DOC, Ext.USER, Ext.TEST):
        update_changed(nb_path, ext, src_mtime, changed_because)

    # Stop if no changes
    if not (changed_because["exists"] or changed_because["mtime"]):
        _log.info(f"=> Skip {nb_path} (source unchanged)")
        return False

    # Load input file
    with nb_path.open("r", encoding="utf-8") as nb_file:
        nb = json.load(nb_file)

    # Get cells to exclude, also ones with notebook xrefs
    had_tag = set()  # if tag occurred at all
    exclude_cells = {n: [] for n in exclude_tags}
    xref_cells = {}  # {cell-index: [list of line indexes]}
    for cell_index, cell in enumerate(nb[NB_CELLS]):
        # Get tags for cell
        cell_tags = set(cell["metadata"].get("tags", []))
        for c in cell_tags:
            try:
                had_tag.add(Tags(c))
            except ValueError:  # not in Tags enum
                pass
        # Potentially add to lists of excluded cells
        for name, ex_tags in exclude_tags.items():
            if cell_tags & ex_tags:
                # add in reverse order to make delete easier
                exclude_cells[name].insert(0, cell_index)
        # Look for (and save) lines with cross references
        xref_lines = [
            i for i, line in enumerate(cell["source"]) if nb_file_pat.search(line)
        ]
        if xref_lines:
            xref_cells[cell_index] = xref_lines

    # Write output files

    nb_names = [Ext.TEST.value, Ext.DOC.value, Ext.USER.value]
    is_tutorial = had_tag & {Tags.EX, Tags.SOL}
    if is_tutorial:
        nb_names.extend([Ext.EX.value, Ext.SOL.value])
        # Also check these files for changes
        for ext in (Ext.EX, Ext.SOL):
            update_changed(nb_path, ext, src_mtime, changed_because)

    # allow notebook metadata to skip certain outputs (e.g. 'test')
    if NB_IDAES in nb[NB_META]:
        for skip_ext in nb[NB_META][NB_IDAES].get(NB_SKIP, []):
            nb_names.remove(skip_ext)
            if skip_ext in changed_because["exists"]:
                changed_because["exists"].remove(skip_ext)
            _log.info(f"Skipping '{skip_ext}' for notebook '{nb_path}'")

    # Check again if we should skip
    if not (changed_because["exists"] or changed_because["mtime"]):
        _log.info(f"=> Skip {nb_path} (source unchanged)")
        return False

    # ..alright, baby, we're doing this!
    why = "source is newer" if changed_because["mtime"] else "generated files missing"
    _log.info(f"=> Preprocess {nb_path} ({why})")

    # Remove 'id' if found in any cells
    ids_removed = []
    for cell_index, cell in enumerate(nb[NB_CELLS]):
        if "id" in cell:
            ids_removed.append(cell_index)
            del cell["id"]
    if ids_removed:
        if len(ids_removed) > 1:
            _log.info(f"Removed 'id' from {len(ids_removed)} cells")
        else:
            _log.info(f"Removed 'id' from cell {ids_removed[0]}")

    # Set notebook version
    nb["nbformat"] = 4
    nb["nbformat_minor"] = 3

    for name in nb_names:
        nb_copy = nb.copy()
        nb_copy[NB_CELLS] = nb[NB_CELLS].copy()
        # Fix (any) cross-references to use current file extension ('name')
        saved_source = []  # save (index, orig-source) for all changed cells
        for cell_index, cell in enumerate(nb_copy[NB_CELLS]):
            if cell_index not in xref_cells or cell_index in exclude_cells[name]:
                continue
            cs = cell["source"]  # alias
            saved_source.append((cell_index, cs.copy()))  # save orig
            for line_index in xref_cells[cell_index]:
                subst = nb_file_pat.sub(nb_file_subs[name], cs[line_index])
                cs[line_index] = subst
        # Delete excluded cells
        for index in exclude_cells[name]:
            del nb_copy[NB_CELLS][index]  # indexes are in reverse order
        # Generate output file
        nbcopy_path = ext_path(nb_path, name=name)
        _log.debug(f"Generate '{name}' file: {nbcopy_path}")
        with nbcopy_path.open("w") as nbcopy_file:
            json.dump(nb_copy, nbcopy_file)
        # Restore modified sources
        for i, s in saved_source:
            nb[NB_CELLS][i]["source"] = s

    dur = time.time() - t0
    _log.info(f"Preprocessed notebook {nb_path} in {dur:.2f} seconds")
    return True


# -------------
# Clean
# -------------


def clean(srcdir=None):
    src_path = find_notebook_root(Path(srcdir)) / NB_ROOT
    toc = read_toc(src_path)
    t0 = time.time()
    results = find_notebooks(src_path, toc, _ro)
    dur = time.time() - t0
    n = len(results)
    n_removed = sum(results.values())
    n_skipped = n - n_removed
    _log.info(
        f"Processed {n} notebooks (removed code cells from {n_removed} / "
        f"did nothing for {n_skipped}) in {dur:.1f} seconds"
    )
    Commands.subheading(f"removed {n_removed}, no action {n_skipped}")


def _ro(nb_path: Path, **kwargs):
    """Remove output cells"""
    nb = json.load(nb_path.open("r", encoding="utf-8"))
    changed = False
    for cell in nb[NB_CELLS]:
        if "cell_type" not in cell:
            raise KeyError(f"Notebook cell missing key 'cell_type' in {nbpath}")
        if cell["cell_type"] == "code":
            if "outputs" not in cell:
                raise KeyError(f"Notebook cell missing key 'outputs' in {nbpath}")
            if cell["outputs"]:
                cell["outputs"] = []
                changed = True
    if changed:
        with nb_path.open("w", encoding="utf-8") as f:
            json.dump(nb, f)
        _log.debug(f"Removed code cell output(s) from {nb_path}")
    return changed


# ---------------
# List skipped
# ---------------


def skipped(srcdir=None):
    src_path = find_notebook_root(Path(srcdir)) / NB_ROOT
    toc = read_toc(src_path)
    smap = {}
    find_notebooks(src_path, toc, _skipped, smap=smap)

    # print results in 'smap'
    # - get column-width for tags
    max_len = max(
        (sum((len(tag) for tag in v)) + (2 * (len(v) - 1)) for v in smap.values())
    )
    # - print each result
    print()
    for k in sorted(list(smap.keys())):
        tag_str = ", ".join(smap[k])
        tag_str += " " * (max_len - len(tag_str))
        file_str = str(k)
        print(f"{tag_str} | {file_str}")


def _skipped(nb_path: Path, smap=None, **kwargs):
    """Print which notebooks have something skipped"""
    with open(nb_path, mode="r", encoding="utf-8") as fp:
        nb = json.load(fp)
    if NB_IDAES in nb[NB_META]:
        skipped = nb[NB_META].get(NB_IDAES, {}).get(NB_SKIP, [])
        if skipped:
            smap[nb_path] = sorted(skipped)


# -------------
# Black
# -------------


def black(srcdir=None):
    src_path = find_notebook_root(Path(srcdir)) / NB_ROOT
    commandline = ["black", "--include", ".*_src\\.ipynb", str(src_path)]
    add_vb_flags(_log, commandline)
    check_call(commandline)


# --------------------
#  Jupyterbook (build)
# --------------------


def _get_nb_path(source_dir: str, dev: bool) -> Path:
    """Get path to notebooks given source code directory."""
    path = find_notebook_root(Path(source_dir))
    path /= NB_ROOT
    if dev:
        path /= "_dev"
        path /= NB_ROOT
    if not path.is_dir():
        raise FileNotFoundError(f"Could not find directory: {path}")
    return path


def jupyterbook(srcdir=None, quiet=0, dev=False):
    path = _get_nb_path(srcdir, dev)
    cwd = os.getcwd()
    _log.info(f"Running build in directory: {path}")
    os.chdir(path)
    try:
        commandline = ["jupyter-book", "build", str(path)]
        if dev:
            commandline.extend(["--path-output", str(path)])
        if quiet > 0:
            quiet = min(quiet, 2)
            commandline.append(f"-{'q' * quiet}")
        else:
            add_vb_flags(_log, commandline)
        # run build
        check_call(commandline)
    finally:
        os.chdir(cwd)


# -------------
#    View
# -------------


def view_docs(srcdir=None):
    src_path = find_notebook_root(Path(srcdir)) / NB_ROOT
    docs_path = src_path / "_build" / "html"
    if not docs_path.is_dir():
        raise FileNotFoundError(f"Could not find directory: {docs_path}")

    url = docs_path.absolute().as_uri() + "/index.html"
    webbrowser.open_new(url)
    return 0


# ----------------
#  Modify config
# ----------------
def modify_conf(
    config_file=None,
    cache_file=None,
    show=False,
    execute=None,
    timeout=None,
    sphinx=False,
):
    # Load configuration file
    with config_file.open("r", encoding="utf-8") as f:
        conf = yaml.safe_load(f)

    def update_value(value, k1, k2):
        """Update value in file at k1/k2."""
        if value is None:
            return
        name = ".".join((k1, k2))
        try:
            orig = conf[k1][k2]
        except KeyError:
            raise KeyError(f"No key {name} found in: {config_file}")
        if orig != value:
            _log.info(f"Set value for {name} from '{orig}' to '{value}'")
            conf[k1][k2] = value
            return True
        return False

    # Set values, aborting on missing keys
    try:
        changed = (
            update_value(execute, "execute", "execute_notebooks")
            or update_value(timeout, "execute", "timeout")
            or update_value(cache_file, "execute", "cache")
        )
    except KeyError:
        return -1

    # Update configurations
    if changed:
        Commands.subheading(
            f"Writing modified Jupyterbook config to file: {config_file}"
        )
        with config_file.open("w", encoding="utf-8") as f:
            yaml.dump(conf, f)
    if sphinx:
        Commands.subheading(f"Updating Sphinx config file")
        commandline = ["jupyter-book", "config", "sphinx", str(config_file.parent)]
        check_call(commandline)

    if show:

        def file_hdr(name):
            print(f"\n# {'-' * 10} {name} {'-' * 10}\n")

        file_hdr(config_file)
        with config_file.open("r", encoding="utf-8") as f:
            for line in f:
                print(line, end="")
        if sphinx:
            sphinx_conf = config_file.parent / "conf.py"
            file_hdr(sphinx_conf)
            with sphinx_conf.open("r", encoding="utf-8") as f:
                for line in f:
                    print(line, end="")

    return 0


# -------------
#  Commandline
# -------------


class Commands:
    @classmethod
    def pre(cls, args):
        cls.heading("Pre-process notebooks")
        return cls._run("pre-process notebooks", preprocess, srcdir=args.dir)

    @classmethod
    def skipped(cls, args):
        cls.heading("Find notebooks which skip pre-processing steps")
        cls.subheading("Notebooks skipping 'test' will not be tested")
        return cls._run("find skipped", skipped, srcdir=args.dir)

    @classmethod
    def build(cls, args):
        dv = " [dev]" if args.dev else ""
        if not args.no_pre:
            cls.heading(f"Pre-process notebooks{dv}")
            cls._run(
                f"pre-process notebooks{dv}", preprocess, srcdir=args.dir, dev=args.dev
            )
        cls.heading(f"Build Jupyterbook{dv}")
        result = cls._run(
            f"build jupyterbook{dv}",
            jupyterbook,
            srcdir=args.dir,
            quiet=args.quiet,
            dev=args.dev,
        )
        return result

    @classmethod
    def conf(cls, args):
        cls.heading("Modify configuration files")
        root_dir = find_notebook_root(Path(args.dir))
        config_file = root_dir / NB_ROOT / "_config.yml"
        if not config_file.exists():
            _log.error(f"Config file not found at: {config_file}")
            _log.error(
                "Root directory can be set with '-d/--dir'. Current value:"
                f" {root_dir.absolute()}"
            )
            return -1
        return cls._run(
            "Modify configuration",
            modify_conf,
            config_file=config_file,
            cache_file=args.cache_file,
            show=args.show,
            execute=args.execute,
            timeout=args.timeout,
            sphinx=args.sphinx,
        )

    @classmethod
    def view(cls, args):
        cls.heading("View Jupyterbook documentation")
        return cls._run("view jupyterbook", view_docs, srcdir=args.dir)

    @classmethod
    def clean(cls, args):
        if not args.yes:
            stop = None
            print(
                "WARNING: This action will remove the results of execution for "
                "ALL notebooks"
            )
            while stop is None:
                response = input("Continue [y/N]? ")
                if response == "":
                    stop = True
                elif len(response) > 1:
                    print("Please answer with one letter: y or n")
                else:
                    r = response[0].lower()
                    if r == "y":
                        stop = False
                    elif r == "n":
                        stop = True
                    else:
                        print("Please answer with one letter: y or n")
            if stop:
                print("Action canceled")
                return 0
        cls.heading("Remove output cells in generated notebooks")
        return cls._run("remove output cells", clean, srcdir=args.dir)

    @classmethod
    def black(cls, args):
        cls.heading("Format code in notebooks with Black")
        return cls._run("format notebook code", black, srcdir=args.dir)

    @classmethod
    def gui(cls, args):
        from idaes_examples import browse

        cls.heading(f"Load notebooks into GUI")
        nb_dir = browse.find_notebook_dir().parent
        cls._run(f"pre-process notebooks", preprocess, srcdir=nb_dir)
        browse.set_log_level(_log.getEffectiveLevel())
        nb = browse.Notebooks()
        if args.console:
            for val in nb._sorted_values:
                pth = Path(val.path).relative_to(Path.cwd())
                print(f"{val.type}{' '*(10 - len(val.type))} {val.title} -> {pth}")
            status = 0
        else:
            status = browse.gui(nb)
        return status

    @classmethod
    def where(cls, args):
        from idaes_examples import browse

        nb_dir = browse.find_notebook_dir()
        print(f"{nb_dir}")

    @classmethod
    def new(cls, args):
        from idaes_examples import nbnew

        app = nbnew.App()
        if args.git == "none":
            app.git_program = None
        elif args.git is not None:
            app.git_program = args.git

        status = app.run()

        return status

    @staticmethod
    def _run(name, func, **kwargs):
        try:
            func(**kwargs)
        except FileNotFoundError as err:
            _log.error(f"During '{name}': {err}")
            _log.error(
                "Check that your working or `-d/--dir` directory contains the Jupyter "
                "source notebooks"
            )
            return -2
        except Exception as err:
            _log.error(f"During '{name}': {err}")
            _log.error(traceback.format_exc())
            return -1

    @staticmethod
    def heading(message):
        print(f"-> {message}")

    @staticmethod
    def subheading(message):
        print(f"   {message}")


def timeout_duration(s):
    """Parse a timeout into an int, raise a ValueError if out of range."""
    v = int(s)
    if v < 1 or v > 60 * 60 * 24:
        raise ValueError("timeout")
    return v


def main():
    p = argparse.ArgumentParser()
    add_vb(p)
    commands = p.add_subparsers(
        title="Commands", help="Commands to run", required=True, dest="command"
    )
    subp = {}
    for name, desc in (
        ("pre", "Pre-process notebooks"),
        ("conf", "Modify Jupyterbook configuration"),
        ("build", "Build Jupyterbook"),
        ("view", "View Jupyterbook"),
        ("clean", "Clean generated files"),
        ("black", "Format code in notebooks with Black"),
        ("gui", "Graphical notebook browser"),
        ("skipped", "List notebooks tagged to skip some pre-processing"),
        ("where", "Print example notebook directory path"),
        ("new", "Terminal-based UI for starting a new notebook"),
    ):
        subp[name] = commands.add_parser(name, help=desc)
        if name != "where":
            subp[name].add_argument(
                "-d", "--dir", help="Source directory (default=<current>)", default=None
            )
        add_vb(subp[name], dest=f"vb_{name}")
    subp["build"].add_argument(
        "--no-pre",
        action="store_true",
        help="skip pre-processing",
        default=False,
    )
    subp["build"].add_argument(
        "--quiet",
        "-q",
        action="count",
        help=" -q means no sphinx status, -qq also turns off warnings",
        default=0,
    )
    subp["build"].add_argument(
        "--dev",
        action="store_true",
        help="Build development notebooks (only)",
        default=False,
    )
    subp["clean"].add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation and perform action",
        default=False,
    )
    subp["conf"].add_argument(
        "--execute",
        dest="execute",
        default=None,
        choices=["auto", "force", "cache", "off"],
        help=f"Set JB config execute.execute_notebooks value",
    )
    subp["conf"].add_argument(
        "--cache-file",
        dest="cache_file",
        default=None,
        help=f"Set JB config execute.cache value",
    )
    subp["conf"].add_argument(
        "--timeout",
        dest="timeout",
        type=timeout_duration,
        default=None,
        help=f"Set JB config execute.timeout value (1..86400 seconds)",
    )
    subp["conf"].add_argument(
        "--show", action="store_true", help="Print config contents to console"
    )
    subp["conf"].add_argument(
        "--sphinx", action="store_true", help="Run JB command to update Sphinx conf.py"
    )
    subp["gui"].add_argument("--console", "-c", action="store_true", dest="console")
    subp["gui"].add_argument(
        "--stderr",
        "-e",
        action="store_true",
        default=False,
        dest="log_console",
        help=(
            "Print logs to the console "
            "(stderr) instead of redirecting "
            "them to a file in ~/.idaes/logs"
        ),
    )
    subp["new"].add_argument("-g", "--git", help="Set Git executable (default=git). "
                                                 "Use 'none' to disable Git.")
    args = p.parse_args()
    subvb = getattr(args, f"vb_{args.command}")
    use_vb = subvb if subvb > args.vb else args.vb
    for logger in _log, util_log:
        process_vb(logger, use_vb)
    # give 'args.dir' a default of ".", but remember whether user gave this value
    if hasattr(args, "dir"):
        if args.dir is None:
            args.dir, args.user_dir = ".", False
        else:
            args.user_dir = True
    func = getattr(Commands, args.command, None)
    if func is None:
        p.print_help()
        sys.exit(0)
    else:
        sys.exit(func(args))


if __name__ == "__main__":
    main()
