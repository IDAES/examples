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


def indent_length(line):
    i = 0
    while line[i] == " ":
        i += 1
    return i


def create_modified_file(path):
    ix_indent, in_ix = 0, False
    # get the mapping to insert
    mapping = get_intersphinx_mapping()
    # change tuples to lists so yaml.dump doesn't do weird things
    for key in mapping:
        mapping[key] = list(mapping[key])
    yaml_text = yaml.dump({"intersphinx_mapping": mapping})
    # Create temporary file with new mapping in it by
    # replacing all lines under 'intersphinx_mapping: ...'
    # with the new YAML text.
    tmp = TemporaryFile("w+")
    for line in path.open("r"):
        if in_ix:
            # Detect end of the block with a return to the same indent
            if indent_length(line) <= ix_indent:
                # write out the new YAML mapping
                indent_spc = " " * ix_indent
                for new_line in yaml_text.split("\n"):
                    tmp.write(indent_spc + new_line + "\n")
                # switch back to 'normal' mode
                in_ix = False
            # else: swallow this line
        elif line.lstrip().startswith("intersphinx_mapping"):
            # switch to 'in intersphinx_mapping' mode
            ix_indent, in_ix = indent_length(line), True
        else:
            tmp.write(line)
    return tmp


def replace_original_file(tmp_f, path):
    tmp_f.seek(0)
    with path.open("w") as f:
        for line in tmp_f:
            f.write(line)


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

    tmp_file = create_modified_file(conf_file)
    replace_original_file(tmp_file, conf_file)

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
