# utf-8

import numpy as np 

import matplotlib.pyplot as plt
from idaes_examples.mod.power_gen.soc_nmpc.soec_attributes import SocAttr


soc_attr = SocAttr()
alias = soc_attr.alias_dict

def Save(m, _var_targets, _data_dict,_t_base):
    """
    update simulation results as dict: {sim_time, data{H2_mass_production,total_power(,CVs)},var_targets{H2_mass_production,total_power},(,CVs)} to __file_path__.folder_name/data.pkl files. 
    Plot and save figures of plant simulation (versus setpoint) results to __file_path__.folder_name/figures_name.svg files. 
    folder_name is determined by the objective function (tracking/economic).

    Args:
        m: Pyomo model
        obj(string): Based on the objective function, either "create_tracking_obj_expr" or "create_economic_obj_expr"
        _var_targets(dict): var_targets = soc_attr.make_sp_trajs(traj_time_set)
        _data_dict(dict): Dictionary of simulation time, results and set points
        _t_base(float): Simulation base time

    Returns:
        None
    """    
    # If there are more variables to save, add them to the list. Note: the defined varaibles are also used for set point saving
    variables_to_save = ['fs.h2_mass_production', 'fs.h2_mass_consumption', 'fs.total_electric_power']

    # Initialize the data dictionary
    if any(key not in _data_dict for key in ['time', 'data', 'var_targets']):
        _data_dict['time'] = []
        _data_dict['data'] = {}
        _data_dict['var_targets'] = {}
    for var in variables_to_save:
        if (var not in _data_dict['data']) or (var not in _data_dict['var_targets']):
            _data_dict['data'][var] = []
            _data_dict['var_targets'][var] = []

    # Update simulation time in _data_dict
    t0 = m.fs.time.first()
    _data_dict['time'].append(_t_base)

    # Update simulation data and set points of vars in _data_dict
    for var in variables_to_save:
        attr = m
        for item in var.split('.'):
            attr = getattr(attr, item)
        _data_dict['data'][var].append(attr[t0].value)
        _data_dict['var_targets'][var].append(_var_targets[alias[var]][_t_base])


def plot(_var_name,_data_dict, scaling_factor):
    fig = plt.figure()
    ax = fig.subplots()
    _sim_time = _data_dict['time']
    _var_data = _data_dict['data'][_var_name]
    _var_sp = _data_dict['var_targets'][_var_name]
    ax.plot(_sim_time, np.array(_var_data)*scaling_factor, 'g-', label=f'{_var_name} Simulation')
    ax.plot(_sim_time, _var_sp, 'r--', label=f'{_var_name} Target')
    ax.set_xlabel('Time (s)')
    #ax.set_xlim((0, _sim_time[-1]))
    #ax.set_ylim((-1.25, 2.5))
    plt.title(f'{_var_name}')

