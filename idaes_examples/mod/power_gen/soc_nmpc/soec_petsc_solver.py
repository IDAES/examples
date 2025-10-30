import idaes.logger as idaeslog
from idaes.core.solvers import petsc

def petsc_initialize(m):
    idaeslog.solver_log.tee = True
    return petsc.petsc_dae_by_time_element(
        m,
        time=m.fs.time,
        # keepfiles=True,
        symbolic_solver_labels=True,
        ts_options={
            "--ts_type": "beuler",
            "--ts_dt": 0.1,
            "--ts_rtol": 1e-03,
            "--ts_adapt_dt_min": 1e-09,
            "--ksp_rtol": 0,
            "--ksp_atol": 1e-16,
            "--snes_type": "newtontr",
            "--ts_monitor": "",
            "--ts_save_trajectory": 1,
            "--ts_trajectory_type": "visualization",
            "--ts_max_snes_failures": 1000,
            "--snes_max_it": 50,
            "--snes_rtol": 0,
            "--snes_stol": 0,
            "--snes_atol": 1e-8,
        },
        skip_initial=False,
        initial_solver="ipopt",
        initial_solver_options={
            'linear_solver': 'ma57',
            'max_iter': 200,
            'tol': 1e-08,
            'halt_on_ampl_error': 'no',
            'bound_push': 1e-06,
            'mu_init': 1e-06,
        },
    )