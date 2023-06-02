import pytest

from idaes_examples import browse


@pytest.mark.unit
def test_dir_finding():
    found = browse.find_notebook_dir()
    assert found is not None
    assert found.is_dir()
