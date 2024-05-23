from pyomo.environ import (
    Constraint,
    Var,
    ConcreteModel,
    Expression,
    Objective,
    TransformationFactory,
    value,
)

import pyomo.environ as pyo

# Todo: Import the above mentioned tools from pyomo.network
from pyomo.network import Arc, SequentialDecomposition
from idaes.core import FlowsheetBlock

from idaes.models.unit_models import (
    PressureChanger,
    Mixer,
    Separator as Splitter,
    Heater,
    CSTR,
    Flash,
    Translator,
)

from idaes.models_extra.column_models import TrayColumn
from idaes.models_extra.column_models.condenser import CondenserType, TemperatureSpec
# Utility tools to put together the flowsheet and calculate the degrees of freedom
from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.initialization import propagate_state
from idaes.core.solvers import get_solver
import idaes.core.util.scaling as iscale

# Import idaes logger to set output levels
import idaes.logger as idaeslog

from idaes_examples.mod.hda import hda_reaction as reaction_props
from idaes.models.properties.activity_coeff_models.BTX_activity_coeff_VLE import (
    BTXParameterBlock,
)

from idaes_examples.mod.hda.hda_ideal_VLE import HDAParameterBlock

def main():
    # Create a Pyomo Concrete Model to contain the problem
    m = ConcreteModel()

    # Add a steady state flowsheet block to the model
    m.fs = FlowsheetBlock(dynamic=False)
    # Property package for benzene, toluene, hydrogen, methane mixture
    m.fs.BTHM_params = HDAParameterBlock()

    # Property package for the benzene-toluene mixture
    m.fs.BT_params = BTXParameterBlock(
        valid_phase=("Liq", "Vap"), activity_coeff_model="Ideal"
    )

    # Reaction package for the HDA reaction
    m.fs.reaction_params = reaction_props.HDAReactionParameterBlock(
        property_package=m.fs.BTHM_params
    )
    # Adding the mixer M101 to the flowsheet
    m.fs.M101 = Mixer(
        property_package=m.fs.BTHM_params,
        inlet_list=["toluene_feed", "hydrogen_feed", "vapor_recycle"],
    )

    # Adding the heater H101 to the flowsheet
    m.fs.H101 = Heater(property_package=m.fs.BTHM_params, has_phase_equilibrium=True)
    
    m.fs.s03 = Arc(source=m.fs.M101.outlet, destination=m.fs.H101.inlet)

    TransformationFactory("network.expand_arcs").apply_to(m)

    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(0.30)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5)
    m.fs.M101.toluene_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5)
    m.fs.M101.toluene_feed.temperature.fix(303.2)
    m.fs.M101.toluene_feed.pressure.fix(350000)

    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "benzene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "toluene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "hydrogen"].fix(0.30)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Vap", "methane"].fix(0.02)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "benzene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "toluene"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "hydrogen"].fix(1e-5)
    m.fs.M101.hydrogen_feed.flow_mol_phase_comp[0, "Liq", "methane"].fix(1e-5)
    m.fs.M101.hydrogen_feed.temperature.fix(303.2)
    m.fs.M101.hydrogen_feed.pressure.fix(350000)

    # Fix the temperature of the outlet from the heater H101
    m.fs.H101.outlet.temperature.fix(600)

    iscale.set_scaling_factor(m.fs.H101.control_volume.heat, 1e-2)

    m.scaling_factor = pyo.Suffix(direction=pyo.Suffix.EXPORT)

    def function(unit):
        print(unit)
        print(unit.default_initializer())
        initializer = unit.default_initializer()
        initializer.initialize(unit, output_level=idaeslog.DEBUG)

    units=[m.fs.M101,m.fs.H101]
    for i in units:
        function(i)

if __name__=='__main__':
    main()