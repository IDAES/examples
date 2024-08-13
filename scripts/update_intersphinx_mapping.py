"""
Update the intersphinx_mapping value in conf.py

You should run this after you run `jupyterbook config sphinx`.
"""
__author__ = "Dan Gunter (LBNL)"

import argparse
import logging
from pathlib import Path
from subprocess import check_call, CalledProcessError
import sys
from tempfile import TemporaryFile
import yaml
from idaes.core.util.intersphinx import get_intersphinx_mapping

CONF_FILE = "_config.yml"

logging.basicConfig()
_log = logging.getLogger("update_intersphinx_mapping")
_log.setLevel(logging.INFO)


def modify(path):
    ix_indent, in_ix = 0, False
    # get the mapping to insert
    mapping = get_intersphinx_mapping()
    # change tuples to lists so yaml.dump doesn't do weird things
    for key in mapping:
        mapping[key] = list(mapping[key])
    # parse & load current config file
    with path.open("r") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.parser.ParserError as err:
            _log.error(f"Parsing config file '{path}': {err}")
            raise
    # modify data in memory
    try:
        data["sphinx"]["config"]["intersphinx_mapping"] = mapping
    except KeyError as err:
        _log.error(f"Modifying config file '{path}': {err} ")
        raise
    # dump modified data
    with path.open("w") as f:
        yaml.dump(data, f)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-d", "--dir",
                    help="Directory containing conf.py (default=.)",
                    default=None)
    ap.add_argument("-c", "--command",
                    action="store_true",
                    help="Run `jupyter-book config sphinx <DIR>` "
                         "after successful update")
    p = ap.parse_args()
    if p.dir is None:
        doc_dir = Path(".")
    else:
        doc_dir = Path(p.dir)

    conf_file = doc_dir / CONF_FILE
    if not conf_file.exists():
        print(f"Config file `{CONF_FILE}` not found in `{doc_dir}`")
        sys.exit(1)

    _log.info(f"Modifying configuration file: {conf_file}")

    try:
        modify(conf_file)
    except Exception as err:
        _log.fatal("Could not create modified file")
        sys.exit(1)

    _log.info(f"Modified configuration file: {conf_file}")

    sphinx_config = doc_dir / "conf.py"

    if p.command:
        cmdline = ["jupyter-book", "config", "sphinx", str(doc_dir)]
        _log.info(f"Running command to update {sphinx_config}: {' '.join(cmdline)}")
        try:
            check_call(cmdline)
        except CalledProcessError as err:
            _log.error(f"Command failed: {' '.join(err.cmd)}")
            _log.error(f"File {sphinx_config} may not be updated")
            sys.exit(1)
    else:
        print(f"\nTo propagate changes to the Sphinx configuration\n"
              f"file, '{sphinx_config}', run the following command:\n\n"
              f"    jupyter-book config sphinx {doc_dir}")
        print("\nAdd '-c'/'--command' to have this script run the command for you")

    sys.exit(0)
