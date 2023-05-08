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
Script to test functionality of key components for use in workshops.

Created on Mon Apr  1 13:32:37 2019

@author: alee
"""

from idaes_examples.mod.notebook_checks import run_checks

print()
check_count = run_checks()
if check_count == 4:
    print("All Good!")
else:
    print("Something is not right. Please contact someone for assistance.")
