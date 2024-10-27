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
"""
Tests for CLC solid phase thermo state block; tests for construction and solve
Author: Chinedu Okoli
"""

import pytest

from pyomo.environ import ConcreteModel, Var
from idaes.core import FlowsheetBlock
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.testing import initialization_tester
from idaes.core.solvers import get_solver
from idaes_examples.mod.diagnostics.gas_solid_contactors.properties.methane_iron_OC_reduction.solid_phase_thermo import (
    SolidPhaseThermoParameterBlock,
)

# Get default solver for testing
solver = get_solver()


# -----------------------------------------------------------------------------
@pytest.fixture(scope="class")
def solid_prop():
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)

    # solid properties and state inlet block
    m.fs.properties = SolidPhaseThermoParameterBlock()

    m.fs.unit = m.fs.properties.build_state_block(
        parameters=m.fs.properties,
        defined_state=True,
    )

    m.fs.unit.flow_mass.fix(1)
    m.fs.unit.temperature.fix(1183.15)
    m.fs.unit.mass_frac_comp["Fe2O3"].fix(0.45)
    m.fs.unit.mass_frac_comp["Fe3O4"].fix(1e-9)
    m.fs.unit.mass_frac_comp["Al2O3"].fix(0.55)

    return m


def test_build_inlet_state_block(solid_prop):
    assert isinstance(solid_prop.fs.unit.dens_mass_skeletal, Var)
    assert isinstance(solid_prop.fs.unit.enth_mol_comp, Var)
    assert isinstance(solid_prop.fs.unit.enth_mass, Var)
    assert isinstance(solid_prop.fs.unit.cp_mol_comp, Var)
    assert isinstance(solid_prop.fs.unit.cp_mass, Var)


def test_setInputs_state_block(solid_prop):
    assert degrees_of_freedom(solid_prop.fs.unit) == 0


def test_initialize(solid_prop):
    initialization_tester(solid_prop)
