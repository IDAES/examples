#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2023 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################
"""
Tests for notebooks (without running them)
"""
# stdlib
import json
import os
from pathlib import Path
import re
import subprocess

# third-party
import pytest

# package
from idaes_examples.util import NotebookCollection, NB_CELLS
from idaes_examples.build import _get_cell_title, _get_header_cell, _get_header_meta

#  Fixtures
# ----------


@pytest.fixture(scope="module")
def notebook_coll() -> NotebookCollection:
    return NotebookCollection()


#  Tests
# -------


def test_has_some_notebooks(notebook_coll):
    notebooks = notebook_coll.get_notebooks()
    assert len(notebooks) > 0
    for nb_path in notebooks:
        assert nb_path.exists()
        assert nb_path.stat().st_size > 0


# Use 'black --check' to test whether syntax is OK in Jupyter notebooks.
# This requires that black[jupyter] has been installed.
def test_black():
    working_dir = Path(__file__).parent
    command = ["black", "--check", "--include", ".*_src\\.ipynb", str(working_dir)]
    proc = subprocess.Popen(command, stderr=subprocess.PIPE)
    _, stderr_data = proc.communicate(timeout=20)
    if proc.returncode != 0:
        # print out errors for pytest's captured stdout
        failed_names = []
        for line in stderr_data.decode("utf-8").split(os.linesep):
            if line.startswith("would"):
                tokens = line.split()
                name = "??"
                for i, tok in enumerate(tokens):
                    if "\\" in tok or "/" in tok:
                        name = " ".join(tokens[i:])
                        break
                print(f"FAILED: {name}")
        assert False, f"Black format check failed"


def test_missing_stale(notebook_coll):
    missing, stale = notebook_coll.missing, notebook_coll.stale
    print(f"got: missing=[{missing}] stale=[{stale}]")
    if missing or stale:
        msg = []
        if missing:
            msg.append(
                f"{len(missing)} missing derived notebooks: "
                f"{', '.join([str(m) for m in missing])}"
            )
        if stale:
            msg.append(
                f"{len(stale)} notebooks with stale derivations "
                "(need to be re-executed):"
            )
            for i, (key, val) in enumerate(stale.items()):
                msg.append(
                    f"({i + 1})  {key}: "
                    f"{', '.join([f'{v[0].name} ({v[1]})' for v in val])}"
                )
        pytest.fail("\n".join(msg))


def test_header(notebook_coll):
    notebooks = notebook_coll.get_notebooks()
    assert len(notebooks) > 0

    errors = []
    base_path = None
    for path in notebooks:
        if base_path is None:
            base_path = get_base_path(path)
        rel_path = path.relative_to(base_path)
        # print(f"Notebook: {rel_path}")  # debug
        with path.open("r", encoding="utf-8") as f:
            nb = json.load(f)
            cells = nb[NB_CELLS]
            assert len(cells) > 0
            header_idx = _get_header_cell(cells)
            if header_idx < 0:
                errors.append(f"{rel_path}: Missing header cell")
                continue
            header = cells[header_idx]
            header_meta = _get_header_meta(header)
            if header_meta is None:
                errors.append(f"{rel_path}: Missing or bad header metadata")
                continue
            # check required keys
            required_keys = {"author": False, "maintainer": False}
            for field in header_meta:
                key = field.lower()
                if key in required_keys:
                    required_keys[key] = True
            missing_keys = [k for k in required_keys if not required_keys[k]]
            if missing_keys:
                mk_str = ",".join(missing_keys)
                errors.append(f"{rel_path}: Missing required metadata keys: {mk_str}")

    if errors:
        print(f"\n[[ {len(errors)} errors ]] base: {base_path}\n")
        for i, e in enumerate(errors):
            print(f"{i + 1:2d}) {e}")
        print()
    assert len(errors) == 0


def get_base_path(p):
    while p.stem != "notebooks":
        p = p.parent
    return p
