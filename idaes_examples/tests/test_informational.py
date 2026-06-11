#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2026 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################
"""
Fake 'test' that provides information
"""

import pytest
from warnings import warn


@pytest.mark.unit
def test_info():
    warn(
        "\n"
        + "+"
        + "-" * 48
        + "+"
        + "\n| These are the Python utility and script tests. |"
        "\n| To perform notebook tests, run 'pytest' in the |"
        "\n| 'idaes_examples' package directory.            |\n"
        + "+"
        + "-" * 48
        + "+"
        + "\n"
    )
