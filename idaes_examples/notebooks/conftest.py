"""
Run pre-processing before tests to guarantee the presence of *_test.ipynb notebooks.
"""
from idaes_examples import build
from pathlib import Path


g_pre = -1  # number of pre-processed notebooks


def pytest_configure(config):
    global g_pre
    if g_pre < 0:
        g_pre = 0
        p = Path(build.__file__).parent
        g_pre = build.preprocess(p)


def pytest_report_collectionfinish(config, start_path, startdir, items):
    return f"{g_pre} Jupyter Notebooks preprocessed"
