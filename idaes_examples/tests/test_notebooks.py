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
import datetime
import os
from pathlib import Path
import re
import subprocess
from typing import List

# third-party
import pytest

# package
from idaes_examples.util import find_notebook_root, find_notebooks, read_toc
from idaes_examples.util import ExtAll, new_ext, Ext

#  Fixtures
# ----------

@pytest.fixture(scope="module")
def notebooks() -> List[Path]:
    src_path = find_notebook_root()
    assert src_path is not None, "Cannot find root directory"
    nb_path = src_path / "notebooks"
    assert nb_path.is_dir(), f"Cannot find 'notebooks' dir in root: {src_path}" 
    toc = read_toc(nb_path)

    notebooks = []

    def add_notebook(p, **kwargs):
        notebooks.append(p)

    find_notebooks(nb_path, toc, callback=add_notebook)
    return notebooks


#  Tests
# -------

def test_has_some_notebooks(notebooks: List[Path]):
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
                    if '\\' in tok or '/' in tok:
                        name = ' '.join(tokens[i:])
                        break
                print(f"FAILED: {name}")
        assert False, f"Black format check failed"

def test_missing_stale(notebooks: List[Path]):
    stale, missing = {}, []
    for p in notebooks:
        assert p.exists()
        p_info = p.stat()
        for ext in ExtAll:
            q = new_ext(p, ext.value)
            if ext is Ext.DOC:
                if not q.exists():
                    missing.append(q)
            if q.exists():
                q_info = q.stat()
                delta = q_info.st_mtime - p_info.st_mtime
                if delta < 0:
                    td = datetime.timedelta(seconds=-delta)
                    if not p in stale:
                        stale[p] = []
                    stale[p].append((q, td))
    if missing or stale:
        msg = []
        if missing:
            msg.append(f"{len(missing)} missing derived notebooks: {', '.join([str(m) for m in missing])}")
        if stale:
            msg.append(f"{len(stale)} notebooks with stale derivations (need to be re-executed):")
            for i, (key, val) in enumerate(stale.items()):
                msg.append(f"({i + 1})  {key}: {', '.join([f'{v[0].name} ({v[1]})' for v in val])}")
        pytest.fail("\n".join(msg))