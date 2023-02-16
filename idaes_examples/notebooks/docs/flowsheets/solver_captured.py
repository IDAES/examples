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
Captured sover
"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time

#
from pyomo.environ import value


class ModelWidget:
    def __init__(self, model, report=None):
        self._model = model
        self._report = report if report else self._status_report
        self._result = None
        self._text = ""

    def solve(self, solver):
        solver = CapturedSolver(solver)
        self._result = solver.solve(self._model)
        self._text = solver.ouput_text
        return self._result

    def report(self):
        return self._report(self._model, self._result)

    def output(self):
        return self._text

    @staticmethod
    def _status_report(m, result):
        text = ""
        for i, solve in enumerate(result["Solver"]):
            text += f"Solve {i + 1}: {solve['Status']} in {solve['Time']}s\n"
        return text


class CapturedSolver:
    def __init__(self, solver):
        self._slv = solver
        self._outcb = self._save_output_lines
        self._outsep = "%%%"
        self._output = []

    def solve(self, model, **kwargs):
        return self._solve_captured(model)

    @property
    def ouput_text(self):
        p = self._output.index(self._outsep)
        output = self._output if p == -1 else self._output[:p]
        return "\n".join(output)

    def _save_output_lines(self, lines):
        self._output.extend(lines)

    def _solve_captured(self, m):
        with TemporaryDirectory() as tempdirname:
            opath = Path(tempdirname) / "solver.txt"
            ofile = opath.open(mode="w", encoding="utf-8")
            filename = opath.name
            result = {}
            tailed = Thread(
                target=self._tail_file, args=(filename, self._outsep, self._outcb, result)
            )
            proc = Thread(
                target=self._run_captured,
                args=(self._slv.solve, (m,), {"tee": True}, ofile, self._outsep),
            )
            tailed.start()
            proc.start()
            while proc.is_alive():
                time.sleep(0.1)
            proc.join()
            tailed.join()
        return result

    @staticmethod
    def _run_captured(target, args, kwargs, ofile, sep):
        save_stdout = sys.stdout
        sys.stdout = ofile
        result = None
        try:
            result = target(*args, **kwargs)
        finally:
            ofile.write("\n")
            ofile.write(sep)
            ofile.write("\n")
            if result is None:
                ofile.write("{}")
            else:
                # append JSON result to output file
                ofile.write(json.dumps(result.json_repn()))
            ofile.write("\n")
            ofile.write(sep)
            ofile.write("\n")
            ofile.close()
            sys.stdout = save_stdout

    @staticmethod
    def _tail_file(filename, sep, output_cb, result):
        f = open(filename, "r", encoding="utf-8")
        all_data = []
        num_sep = 0
        partial_line = ""
        while num_sep < 2:
            data = f.read()
            if data:
                lines = data.split("\n")
                if partial_line:
                    lines[0] = partial_line + lines[0]
                if not data.endswith("\n"):
                    partial_line = lines[-1]
                    lines = lines[:-1]
                else:
                    partial_line = ""
                output_cb(lines)
                all_data.extend(lines)
                num_sep += sum((ln == sep for ln in lines))
            else:
                time.sleep(0.5)
        # parse JSON result back to Python dict
        if num_sep >= 2:
            n1 = all_data.index(sep)
            n2 = all_data.index(sep, n1 + 1)
            json_text = "".join(all_data[n1 + 1: n2])
            r = json.loads(json_text)
            result.update(r)


