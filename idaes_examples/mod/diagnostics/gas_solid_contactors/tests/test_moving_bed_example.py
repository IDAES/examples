##############################################################################
# Institute for the Design of Advanced Energy Systems Process Systems
# Engineering Framework (IDAES PSE Framework) Copyright (c) 2018-2019, by the
# software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia
# University Research Corporation, et al. All rights reserved.
#
# Please see the files COPYRIGHT.txt and LICENSE.txt for full copyright and
# license information, respectively. Both files are also available online
# at the URL "https://github.com/IDAES/idaes-pse".
##############################################################################
import pytest
import idaes_examples.mod.diagnostics.gas_solid_contactors.example as example
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.model_diagnostics import check_parallel_jacobian
import pyomo.environ as pyo
from pyomo.contrib.incidence_analysis import IncidenceGraphInterface


class TestMovingBedExample:

    def test_original_model(self):
        model = example.create_original_model()
        assert degrees_of_freedom(model) == 10
        # Make sure the model doesn't solve
        solver = pyo.SolverFactory("ipopt")
        solver.options["max_iter"] = 10
        res = solver.solve(model)
        assert not pyo.check_optimal_termination(res)

    def test_original_square_model(self):
        model = example.create_original_square_model()
        assert degrees_of_freedom(model) == 0
        igraph = IncidenceGraphInterface(model)
        vdm, cdm = igraph.dulmage_mendelsohn()
        # Make sure the model is structurally singular
        assert len(vdm.unmatched) == 10
        assert len(cdm.unmatched) == 10

    def test_model_with_new_variable_and_constraint(self):
        # First attempt to fix the model
        model = example.create_square_model_with_new_variable_and_constraint()
        assert degrees_of_freedom(model) == 0
        igraph = IncidenceGraphInterface(model)
        vdm, cdm = igraph.dulmage_mendelsohn()
        # Make sure the model is *not* structurally singular
        assert not vdm.unmatched
        assert not cdm.unmatched

        # Make sure the model still doesn't solve
        example.free_degrees_of_freedom(model)
        solver = pyo.SolverFactory("ipopt")
        solver.options["max_iter"] = 10
        res = solver.solve(model)
        assert not pyo.check_optimal_termination(res)
        example.fix_degrees_of_freedom(model)

        # Make sure the model is numerically singular
        parallel = check_parallel_jacobian(model, direction="row", tolerance=1e-8)
        assert len(parallel) == 11

    def test_corrected_model(self):
        model = example.create_corrected_square_model()

        igraph = IncidenceGraphInterface(model)
        vdm, cdm = igraph.dulmage_mendelsohn()
        # Make sure the model is *not* structurally singular
        assert not vdm.unmatched
        assert not cdm.unmatched

        example.free_degrees_of_freedom(model)
        assert degrees_of_freedom(model) == 10

        # Make sure the model solves
        solver = pyo.SolverFactory("ipopt")
        solver.options["max_iter"] = 10
        res = solver.solve(model)
        assert pyo.check_optimal_termination(res)


if __name__ == "__main__":
    pytest.main([__file__])
