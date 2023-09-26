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
