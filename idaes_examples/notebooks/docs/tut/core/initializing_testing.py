# Import required packages
from idaes.models_extra.power_generation.properties.natural_gas_PR import get_prop
from pyomo.environ import (
    ConcreteModel,
    SolverFactory,
    value,
    units,
    TransformationFactory,
    Expression,
)
from idaes.core import FlowsheetBlock
from idaes.core.util.initialization import propagate_state
import idaes.logger as idaeslog
from idaes.models.properties import iapws95
from idaes.models.unit_models import Feed
from idaes.models.unit_models.heater import Heater
from idaes.models.unit_models.heat_exchanger import (
    HeatExchanger,
    delta_temperature_amtd_callback,
)
from pyomo.network import Arc, SequentialDecomposition
from idaes.core.util.model_statistics import degrees_of_freedom

# Create the ConcreteModel and the FlowsheetBlock, and attach the flowsheet block to it.
m = ConcreteModel()

m.fs = FlowsheetBlock(dynamic=False)

m.fs.properties = iapws95.Iapws95ParameterBlock()

m.fs.feed = Feed(property_package=m.fs.properties)
m.fs.heater = Heater(property_package=m.fs.properties)
m.fs.heat_exchanger = HeatExchanger(
    delta_temperature_callback=delta_temperature_amtd_callback,
    hot_side_name="shell",
    cold_side_name="tube",
    shell={"property_package": m.fs.properties},
    tube={"property_package": m.fs.properties},
)

m.fs.s01 = Arc(source=m.fs.feed.outlet, destination=m.fs.heat_exchanger.cold_side_inlet)
m.fs.s02 = Arc(
    source=m.fs.heat_exchanger.cold_side_outlet, destination=m.fs.heater.inlet
)
m.fs.s03 = Arc(
    source=m.fs.heater.outlet, destination=m.fs.heat_exchanger.hot_side_inlet
)

TransformationFactory("network.expand_arcs").apply_to(m)
DOF_initial = degrees_of_freedom(m)
print("The initial DOF is {0}".format(DOF_initial))

# Fix the stream inlet conditions
m.fs.feed.flow_mol[0].fix(100)  # mol/s
m.fs.feed.pressure[0].fix(101325)  # Pa
m.fs.feed.enth_mol[0].fix(value(iapws95.htpx(T=293 * units.K, P=101325 * units.Pa)))


m.fs.heat_exchanger.overall_heat_transfer_coefficient[0].fix(500)  # W/m2/K
m.fs.heat_exchanger.area.fix(50)


m.fs.heater.outlet.enth_mol.fix(
    value(iapws95.htpx(T=1073 * units.K, P=101325 * units.Pa))
)

DOF_initial = degrees_of_freedom(m)
print("The DOF is {0}".format(DOF_initial))

# Provide initial guess for the shell inlet and create tear stream
m.fs.heat_exchanger.shell_inlet.flow_mol.fix(100)  # mol/s
m.fs.heat_exchanger.shell_inlet.enth_mol[0].fix(
    value(iapws95.htpx(T=1073 * units.K, P=101325 * 1.5 * units.Pa))
)
m.fs.heat_exchanger.shell_inlet.pressure[0].fix(101325)  # Pa
m.fs.s03_expanded.deactivate()

DOF_initial = degrees_of_freedom(m)
print("The DOF is {0} after creating tear stream".format(DOF_initial))

m.fs.report()

m.fs.feed.initialize(outlvl=idaeslog.INFO)
propagate_state(m.fs.s01)
m.fs.report()
m.fs.heat_exchanger.initialize(outlvl=idaeslog.INFO)
propagate_state(m.fs.s02)
m.fs.report()
m.fs.heater.initialize(outlvl=idaeslog.INFO)

m.fs.report()

# Solve the model
from idaes.core.solvers import get_solver

solver = get_solver()
results = solver.solve(m, tee=False)

# Reactivate tear stream, and unfix shell side initial conditions
m.fs.heat_exchanger.shell_inlet.flow_mol.unfix()
m.fs.heat_exchanger.shell_inlet.enth_mol[0].unfix()
m.fs.heat_exchanger.shell_inlet.pressure[0].unfix()
m.fs.s03_expanded.activate()

results = solver.solve(m, tee=False)

m.fs.report()
