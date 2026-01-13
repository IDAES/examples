import numpy as np
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.solvers import get_solver
import idaes.logger as idaeslog

def FpcTP_to_FpTPxpc(flow_mol_phase_comp):

    flow_mol_phase = {
        "Vap": 0,
        "Liq": 0,
    }
    mole_frac_phase_comp = {}

    for (p, c) in flow_mol_phase_comp.keys():
        flow_mol_phase[p] += flow_mol_phase_comp[(p, c)]
    for (p, c) in flow_mol_phase_comp.keys():
        if flow_mol_phase[p] == 0.0:
            mole_frac_phase_comp[p, c] = 0.0
        else:
            mole_frac_phase_comp[p, c] = flow_mol_phase_comp[(p, c)] / flow_mol_phase[p]

    return flow_mol_phase, mole_frac_phase_comp


def fix_inlet_states(m):

    eps = 1e-5
    flow_mol_phase_comp_101 = {
        ("Vap", "benzene"): eps,
        ("Vap", "toluene"): eps,
        ("Vap", "hydrogen"): eps,
        ("Vap", "methane"): eps,
        ("Liq", "benzene"): eps,
        ("Liq", "toluene"): 0.30,
    }

    flow_mol_phase_101, mole_frac_phase_comp_101 = FpcTP_to_FpTPxpc(flow_mol_phase_comp_101)

    m.fs.I101.flow_mol_phase[0, "Vap"].fix(flow_mol_phase_101["Vap"])
    m.fs.I101.flow_mol_phase[0, "Liq"].fix(flow_mol_phase_101["Liq"])
    m.fs.I101.mole_frac_phase_comp[0, "Vap", "benzene"].fix(mole_frac_phase_comp_101["Vap", "benzene"])
    m.fs.I101.mole_frac_phase_comp[0, "Vap", "toluene"].fix(mole_frac_phase_comp_101["Vap", "toluene"])
    m.fs.I101.mole_frac_phase_comp[0, "Vap", "hydrogen"].fix(mole_frac_phase_comp_101["Vap", "hydrogen"])
    m.fs.I101.mole_frac_phase_comp[0, "Vap", "methane"].fix(mole_frac_phase_comp_101["Vap", "methane"])
    m.fs.I101.mole_frac_phase_comp[0, "Liq", "benzene"].fix(mole_frac_phase_comp_101["Liq", "benzene"])
    m.fs.I101.mole_frac_phase_comp[0, "Liq", "toluene"].fix(mole_frac_phase_comp_101["Liq", "toluene"])
    m.fs.I101.temperature.fix(303.2)
    m.fs.I101.pressure.fix(350000)

    flow_mol_phase_comp_102 = {
        ("Vap", "benzene"): eps,
        ("Vap", "toluene"): eps,
        ("Vap", "hydrogen"): .30,
        ("Vap", "methane"): .02,
        ("Liq", "benzene"): eps,
        ("Liq", "toluene"): eps,
    }

    flow_mol_phase_102, mole_frac_phase_comp_102 = FpcTP_to_FpTPxpc(flow_mol_phase_comp_102)

    m.fs.I102.flow_mol_phase[0, "Vap"].fix(flow_mol_phase_102["Vap"])
    m.fs.I102.flow_mol_phase[0, "Liq"].fix(flow_mol_phase_102["Liq"])
    m.fs.I102.mole_frac_phase_comp[0, "Vap", "benzene"].fix(mole_frac_phase_comp_102["Vap", "benzene"])
    m.fs.I102.mole_frac_phase_comp[0, "Vap", "toluene"].fix(mole_frac_phase_comp_102["Vap", "toluene"])
    m.fs.I102.mole_frac_phase_comp[0, "Vap", "hydrogen"].fix(mole_frac_phase_comp_102["Vap", "hydrogen"])
    m.fs.I102.mole_frac_phase_comp[0, "Vap", "methane"].fix(mole_frac_phase_comp_102["Vap", "methane"])
    m.fs.I102.mole_frac_phase_comp[0, "Liq", "benzene"].fix(mole_frac_phase_comp_102["Liq", "benzene"])
    m.fs.I102.mole_frac_phase_comp[0, "Liq", "toluene"].fix(mole_frac_phase_comp_102["Liq", "toluene"])
    m.fs.I102.temperature.fix(303.2)
    m.fs.I102.pressure.fix(350000)

    tear_guesses = {
        "flow_mol_phase": {
            (0, "Liq"): flow_mol_phase_101["Liq"],
            (0, "Vap"): flow_mol_phase_102["Vap"],
        },
        "mole_frac_phase_comp": {
            (0, "Liq", "benzene"): mole_frac_phase_comp_101["Liq", "benzene"],
            (0, "Liq", "toluene"): mole_frac_phase_comp_101["Liq", "toluene"],
            (0, "Vap", "benzene"): mole_frac_phase_comp_102["Vap", "benzene"],
            (0, "Vap", "toluene"): mole_frac_phase_comp_102["Vap", "toluene"],
            (0, "Vap", "methane"): mole_frac_phase_comp_102["Vap", "hydrogen"],
            (0, "Vap", "hydrogen"): mole_frac_phase_comp_102["Vap", "methane"],
        },
        "temperature": {0: 303},
        "pressure": {0: 350000},
    }

    return tear_guesses


def initialize_unit(unit):
    from idaes.core.util.exceptions import InitializationError
    import idaes.logger as idaeslog

    optarg = {
        "nlp_scaling_method": "user-scaling",
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 1000,
        "tol": 1e-8,
    }

    try:
        initializer = unit.default_initializer(solver_options=optarg)
        initializer.initialize(unit, output_level=idaeslog.INFO_LOW)
    except InitializationError:
        solver = get_solver(solver_options=optarg)
        solver.solve(unit)


def manual_propagation(m, tear_guesses):
    from idaes.core.util.initialization import propagate_state

    print(f"The DOF is {degrees_of_freedom(m)} initially")
    m.fs.s03_expanded.deactivate()
    print(f"The DOF is {degrees_of_freedom(m)} after deactivating the tear stream")

    for k, v in tear_guesses.items():
        for k1, v1 in v.items():
            getattr(m.fs.s03.destination, k)[k1].fix(v1)

    DOF_initial = degrees_of_freedom(m)

    print(f"The DOF is {degrees_of_freedom(m)} after setting the tear stream")

    optarg = {
        "nlp_scaling_method": "user-scaling",
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 300,
        # "tol": 1e-10,
    }

    solver = get_solver(solver_options=optarg)

    initialize_unit(m.fs.H101) # Initialize Heater
    propagate_state(m.fs.s04)  # Establish connection between Heater and Reactor
    initialize_unit(m.fs.R101) # Initialize Reactor
    propagate_state(m.fs.s05)  # Establish connection between Reactor and First Flash Unit
    initialize_unit(m.fs.F101)  # Initialize First Flash Unit
    propagate_state(m.fs.s06)  # Establish connection between First Flash Unit and Splitter
    propagate_state(m.fs.s07)  # Establish connection between First Flash Unit and Second Flash Unit
    initialize_unit(m.fs.S101)  # Initialize Splitter
    propagate_state(m.fs.s08)  # Establish connection between Splitter and Compressor
    initialize_unit(m.fs.C101)  # Initialize Compressor
    propagate_state(m.fs.s09)  # Establish connection between Compressor and Mixer
    initialize_unit(m.fs.I101)  # Initialize Toluene Inlet
    propagate_state(m.fs.s01)  # Establish connection between Toluene Inlet and Mixer
    initialize_unit(m.fs.I102)  # Initialize Hydrogen Inlet
    propagate_state(m.fs.s02)  # Establish connection between Hydrogen Inlet and Mixer
    initialize_unit(m.fs.M101)  # Initialize Mixer
    propagate_state(m.fs.s03)  # Establish connection between Mixer and Heater
    solver.solve(m.fs.F102)
    propagate_state(m.fs.s10)  # Establish connection between Second Flash Unit and Benzene Product
    propagate_state(m.fs.s11)  # Establish connection between Second Flash Unit and Toluene Product
    propagate_state(m.fs.s12)  # Establish connection between Splitter and Purge Product

    optarg = {
        "nlp_scaling_method": "user-scaling",
        "OF_ma57_automatic_scaling": "yes",
        "max_iter": 300,
        "tol": 1e-8,
    }
    solver = get_solver("ipopt_v2", options=optarg)
    solver.solve(m, tee=False)

    for k, v in tear_guesses.items():
        for k1, v1 in v.items():
            getattr(m.fs.H101.inlet, k)[k1].unfix()

    m.fs.s03_expanded.activate()
    print(
        f"The DOF is {degrees_of_freedom(m)} after unfixing the values and reactivating the tear stream"
    )
    
    
def automatic_propagation(m, tear_guesses):
    
    from pyomo.network import SequentialDecomposition

    seq = SequentialDecomposition()
    seq.options.select_tear_method = "heuristic"
    seq.options.tear_method = "Wegstein"
    seq.options.iterLim = 5

    # Using the SD tool
    G = seq.create_graph(m)
    heuristic_tear_set = seq.tear_set_arcs(G, method="heuristic")
    order = seq.calculation_order(G)

    # Pass the tear_guess to the SD tool
    seq.set_guesses_for(heuristic_tear_set[0].destination, tear_guesses)

    print(f'Tear Stream starts at: {heuristic_tear_set[0].destination.name}')

    for o in order:
        print(o[0].name)

    seq.run(m, initialize_unit)


