import numpy as np
import pandas as pd

import pyomo.environ as pyo

import idaes
from idaes.core.solvers import get_solver
from idaes.core.solvers import use_idaes_solver_configuration_defaults

# Set up time discretization.
pred_step_num = 5
t_step = 75.0  # s
pred_horizon = pred_step_num * t_step

t_start = 1 * 30 * 60
t_end = 2 * 60 * 60

df_full = pd.read_csv("operations_new.csv", index_col=0)

df = df_full
df.reset_index(inplace=True)
df.loc[:, 'hour'] = df.index
df.set_index('hour', inplace=True)

n_hour_point, n_vars = df.shape
t_ramp = 10 * 60
t_settle = 50 * 60

dt_set = [t_start]
scenario_names = ['t_start']
for k in range(n_hour_point - 1):
    dt_set.append(t_ramp)
    dt_set.append(t_settle)
    scenario_names.append('t_ramp')
    scenario_names.append('t_settle')

time_mark_list = [sum(dt_set[:j]) for j in range(len(dt_set) + 1)]
sim_horizon = time_mark_list[-1] #- (t_settle - t_end)

sim_nfe = int((sim_horizon) / t_step)
sim_time_set = np.linspace(0, sim_nfe*t_step, sim_nfe+1)
traj_time_set = np.linspace(0, sim_nfe*t_step+pred_horizon, sim_nfe+pred_step_num+1)
# traj_time_set = np.linspace(0, sim_horizon+pred_horizon, int((sim_horizon+pred_horizon)/50)+1)

# %% Set up ipopt.
use_idaes_solver_configuration_defaults()
idaes.cfg.ipopt.options.nlp_scaling_method = "gradient-based"
idaes.cfg.ipopt.options.halt_on_ampl_error = "no"
#linear_scaling_on_demand = no
# idaes.cfg.ipopt_l1.options.OF_restoration_method = "l1"
# idaes.cfg.ipopt_l1.options.OF_l1_epsilon = 0.5
idaes.cfg.ipopt.options.max_iter = 1000
idaes.cfg.ipopt.options.linear_solver = "ma57"
idaes.cfg.ipopt.options.OF_ma57_pivtol = 1e-06  # default = 1e-08
idaes.cfg.ipopt.options.OF_ma57_automatic_scaling = "yes"
idaes.cfg.ipopt.options.OF_print_info_string = "yes"
idaes.cfg.ipopt.options.OF_warm_start_init_point = "yes"
idaes.cfg.ipopt.options.OF_warm_start_mult_bound_push = 1e-06
idaes.cfg.ipopt.options.OF_warm_start_bound_push = 1e-06
idaes.cfg.ipopt.options.tol = 1e-04  # default = 1e-08
idaes.cfg.ipopt.options.mu_init = 1e-05  # default = 1e-01
idaes.cfg.ipopt.options.bound_push = 1e-06  # default = 1e-02
idaes.cfg.ipopt.options.bound_relax_factor = 1e-06  # default = 1e-08

# idaes.cfg.ipopt.options.constr_viol_tol = 1e-3 # default = 1e-4
solver_v1 = pyo.SolverFactory('ipopt')

solver_options = {
    "nlp_scaling_method": "gradient-based",
    "halt_on_ampl_error": "no",
    "max_iter": 1000,
    "linear_solver": "ma57",
    "ma57_pivtol": 1e-6,
    "ma57_automatic_scaling": "yes",
    "print_info_string": "no",
    "warm_start_init_point": "yes",
    "warm_start_mult_bound_push": 1e-6,
    "warm_start_bound_push": 1e-6,
    "tol": 1e-4,
    "mu_init": 1e-5,
    "bound_push": 1e-6,
    "bound_relax_factor": 1e-6
}
solver_v2 = get_solver("ipopt_v2", options=solver_options, writer_config={"linear_presolve": False, "scale_model": True})


def pass_all_vars_plant(target_model, source_model):
    def get_all_vars(m):
        all_vars = []
        for var in m.component_objects(pyo.Var):
            if isinstance(var, pyo.Var):
                if var.name not in ('fs.p1', 'fs.n1',
                                    'fs.p2', 'fs.n2',
                                    'fs.p3', 'fs.n3',
                                    'fs.soc_module.solid_oxide_cell.fuel_electrode.p',
                                    'fs.soc_module.solid_oxide_cell.fuel_electrode.n',
                                    'fs.p', 'fs.n',
                                    'fs.avg_curr_density_p', 'fs.avg_curr_density_n',
                                    'fs.pointwise_curr_density_p', 'fs.pointwise_curr_density_n',
                                    # var in the controller but not in the plant
                                    ):
                    all_vars.append(var)
        all_vars_temp = [v for v in all_vars if m.fs.time in v.index_set().subsets()]
        return all_vars_temp

    def set_var_ics(var_target, var_source):
        for idxs, v in var_target.items():
            if v.fixed:
                continue
            if type(idxs) == float:
                v.set_value(var_source[idxs].value)
            elif type(idxs) == tuple:
                v.set_value(var_source[tuple([idxs[0], *idxs[1:]])].value)
        return None

    target_model_vars = get_all_vars(target_model)
    source_model_vars = get_all_vars(source_model)
    for var_target, var_source in zip(target_model_vars, source_model_vars):
        set_var_ics(var_target, var_source)

    