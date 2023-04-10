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
Task: Artificial Intelligence/Machine Learning
Subtask: Best Practices Surrogates Optimization - Training Methods
Author: B. Paul
"""

# Import statements
import os
import numpy as np
import pandas as pd
import random as rn
import tensorflow as tf

# Import IDAES libraries
from idaes.core.surrogate.sampling.data_utils import split_training_validation
from idaes.core.surrogate.alamopy import AlamoTrainer
from idaes.core.surrogate.pysmo_surrogate import (PysmoPolyTrainer,
                                                  PysmoRBFTrainer,
                                                  PysmoKrigingTrainer,
                                                  PysmoSurrogate)
from idaes.core.surrogate.sampling.scaling import OffsetScaler
from idaes.core.surrogate.keras_surrogate import KerasSurrogate

# fix environment variables to ensure consist neural network training
os.environ['PYTHONHASHSEED'] = '0'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
np.random.seed(46)
rn.seed(1342)
tf.random.set_seed(62)


def train_load_surrogates(retrain=False):
    """
    Method to check if surrogates exist, load if available and train if needed.
    """

    if retrain is False:
        print('Loading existing surrogate models and training missing models.')
        print('Any training output will print below; otherwise, models will '
              'be loaded without any further output.')
    elif retrain is True:
        print('Training surrogate models.')
        print('Output will appear below.')

    # Import Auto-reformer training data
    np.set_printoptions(precision=6, suppress=True)

    csv_data = pd.read_csv(r'reformer-data.csv')  # 2800 data points
    data = csv_data.sample(n=100)  # randomly sample points for training

    input_data = data.iloc[:, :2]
    output_data = data.iloc[:, 2:]

    # Define labels, and split training and validation data
    input_labels = input_data.columns
    output_labels = output_data.columns

    n_data = data[input_labels[0]].size
    data_training, data_validation = split_training_validation(
        data, 0.8, seed=n_data)  # seed=2800

    # Train surrogates using ALAMO

    if os.path.exists('alamo_surrogate.json') and retrain is False:
        # surrogates JSON already exists, skip training
        # we will load the object into the flowsheet later
        pass
    else:  # need to create ALAMO surrogate object

        trainer = AlamoTrainer(input_labels=input_labels,
                               output_labels=output_labels,
                               training_dataframe=data_training)

        # Set ALAMO options
        trainer.config.constant = True
        trainer.config.linfcns = True
        trainer.config.multi2power = [1, 2]
        trainer.config.monomialpower = [2, 3]
        trainer.config.ratiopower = [1, 2]
        trainer.config.maxterms = [10] * len(output_labels)
        trainer.config.filename = os.path.join(os.getcwd(), 'alamo_run.alm')
        trainer.config.overwrite_files = True

        # Train surrogate (calls ALAMO through IDAES ALAMOPy wrapper)
        success, alm_surr, msg = trainer.train_surrogate()

        # save model to JSON
        alm_surr.save_to_file('alamo_surrogate.json', overwrite=True)

    # Train surrogates using PySMO
    input_data_train = data_training.iloc[:, :2]
    output_data_train = data_training.iloc[:, 2:]
    input_labels = list(input_data_train.columns)
    output_labels = list(output_data_train.columns)

    if os.path.exists('pysmo_poly_surrogate.json') and retrain is False:
        # surrogates JSON already exists, skip training
        # we will load the object into the flowsheet later
        pass
    else:  # need to create PySMO Polynomial surrogate object

        trainer = PysmoPolyTrainer(input_labels=input_labels,
                                   output_labels=output_labels,
                                   training_dataframe=data_training)

        # Set PySMO options
        trainer.config.maximum_polynomial_order = 6
        trainer.config.multinomials = True
        trainer.config.training_split = 0.8
        trainer.config.number_of_crossvalidations = 10

        # Train surrogate (calls PySMO through IDAES Python wrapper)
        poly_train = trainer.train_surrogate()

        # create callable surrogate object
        xmin, xmax = [0.1, 0.8], [0.8, 1.2]
        input_bounds = {input_labels[i]: (xmin[i], xmax[i])
                        for i in range(len(input_labels))}
        poly_surr = PysmoSurrogate(poly_train, input_labels,
                                   output_labels, input_bounds)

        # save model to JSON
        poly_surr.save_to_file('pysmo_poly_surrogate.json', overwrite=True)

    if os.path.exists('pysmo_rbf_surrogate.json') and retrain is False:
        # surrogates JSON already exists, skip training
        # we will load the object into the flowsheet later
        pass
    else:  # need to create PySMO Radial Basis Function surrogate object

        trainer = PysmoRBFTrainer(input_labels=input_labels,
                                  output_labels=output_labels,
                                  training_dataframe=data_training)

        # Set PySMO options
        trainer.config.basis_function = 'gaussian'
        trainer.config.solution_method = 'pyomo'
        trainer.config.regularization = True

        # Train surrogate (calls PySMO through IDAES Python wrapper)
        rbf_train = trainer.train_surrogate()

        # create callable surrogate object
        xmin, xmax = [0.1, 0.8], [0.8, 1.2]
        input_bounds = {input_labels[i]: (xmin[i], xmax[i])
                        for i in range(len(input_labels))}
        rbf_surr = PysmoSurrogate(rbf_train, input_labels,
                                  output_labels, input_bounds)

        # save model to JSON
        rbf_surr.save_to_file('pysmo_rbf_surrogate.json', overwrite=True)

    if os.path.exists('pysmo_krig_surrogate.json') and retrain is False:
        # surrogates JSON already exists, skip training
        # we will load the object into the flowsheet later
        pass
    else:  # need to create PySMO Kriging surrogate object

        trainer = PysmoKrigingTrainer(input_labels=input_labels,
                                      output_labels=output_labels,
                                      training_dataframe=data_training)

        # Set PySMO options
        trainer.config.numerical_gradients = True
        trainer.config.regularization = True

        # Train surrogate (calls PySMO through IDAES Python wrapper)
        krig_train = trainer.train_surrogate()

        # create callable surrogate object
        xmin, xmax = [0.1, 0.8], [0.8, 1.2]
        input_bounds = {input_labels[i]: (xmin[i], xmax[i])
                        for i in range(len(input_labels))}
        krig_surr = PysmoSurrogate(krig_train, input_labels,
                                   output_labels, input_bounds)

        # save model to JSON
        krig_surr.save_to_file('pysmo_krig_surrogate.json', overwrite=True)

    # Train surrogates using Keras

    if os.path.exists('keras_surrogate/') and retrain is False:
        # surrogates folder already exists, skip training
        # we will load the object into the flowsheet later
        pass
    else:  # need to create Keras surrogate files

        # selected settings for regression
        (activation, optimizer, n_hidden_layers,
         n_nodes_per_layer) = 'tanh', 'Adam', 2, 40
        loss, metrics = 'mse', ['mae', 'mse']

        # Create data objects for training using scalar normalization
        n_inputs = len(input_labels)
        n_outputs = len(output_labels)
        x = input_data
        y = output_data

        input_scaler = None
        output_scaler = None
        input_scaler = OffsetScaler.create_normalizing_scaler(x)
        output_scaler = OffsetScaler.create_normalizing_scaler(y)
        x = input_scaler.scale(x)
        y = output_scaler.scale(y)
        x = x.to_numpy()
        y = y.to_numpy()

        # Create Keras Sequential object and build neural network
        model = tf.keras.Sequential()
        model.add(tf.keras.layers.Dense(units=n_nodes_per_layer,
                                        input_dim=n_inputs,
                                        activation=activation))
        for i in range(1, n_hidden_layers):
            model.add(tf.keras.layers.Dense(units=n_nodes_per_layer,
                                            activation=activation))
        model.add(tf.keras.layers.Dense(units=n_outputs))

        # Train surrogate (calls optimizer on neural network and solves
        # for weights)
        model.compile(loss=loss, optimizer=optimizer, metrics=metrics)
        mcp_save = tf.keras.callbacks.ModelCheckpoint('.mdl_wts.hdf5',
                                                      save_best_only=True,
                                                      monitor='val_loss',
                                                      mode='min')
        model.fit(x=x, y=y, validation_split=0.2, verbose=1,
                  epochs=1000, callbacks=[mcp_save])

        # save model to JSON and create callable surrogate object
        xmin, xmax = [0.1, 0.8], [0.8, 1.2]
        input_bounds = {input_labels[i]: (xmin[i], xmax[i])
                        for i in range(len(input_labels))}

        keras_surrogate = KerasSurrogate(model,
                                         input_labels=list(input_labels),
                                         output_labels=list(output_labels),
                                         input_bounds=input_bounds,
                                         input_scaler=input_scaler,
                                         output_scaler=output_scaler)
        keras_surrogate.save_to_folder('keras_surrogate')

    # ALAMO saves a single object, so we can load it when needed later
    # Keras saves a folder of files, and we can load them when needed later
    # PySMO saves a single object for each basis type, we can load them later
