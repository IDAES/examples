"""
Handle pre-processing and filtering of Jupyter Notebooks for pytest.

Note that this replaces some functionality that in theory could be in pytest.ini
"""
from idaes_examples import build
from pathlib import Path
import logging
import os
from typing import List
import pytest


logging.basicConfig()


class NotebookPrep:
    """Simple wrapper for notebook pre-processing state and operations.
    """

    worker_logs = {}

    num_pre = -1
    num_test = 0
    num_coll = 0

    skip_dirs = [f"{p}{os.path.sep}" for p in ("archive", "_dev")]

    @classmethod
    def get_log(cls, config):
        worker_id = os.environ.get("PYTEST_XDIST_WORKER")
        if worker_id is None:
            log = logging.root
        else:
            try:
                log = cls.worker_logs[worker_id]
            except KeyError:
                level, fmt = None, None
                try:
                    level = config.getini("log_file_level")
                except KeyError:
                    pass
                if not level:
                    level = logging.INFO
                try:
                    fmt = config.getini("log_file_format")
                except KeyError:
                    pass
                if not fmt:
                    fmt = "%(asctime)s %(name)s: %(message)s"
                log = logging.getLogger(f"pytest_worker_{worker_id}")
                log.setLevel(level)
                h = logging.FileHandler(f"tests_{worker_id}.log")
                h.setFormatter(logging.Formatter(fmt))
                log.addHandler(h)
                cls.worker_logs[worker_id] = log
        return log

    @classmethod
    def configure(cls, config: pytest.Config):
        log = cls.get_log(config)
        if cls.num_pre < 0:
            log.info("Preprocessing Jupyter notebooks")
            cls.num_pre = 0
            p = Path(build.__file__).parent
            cls.num_pre = build.preprocess(p)

    @classmethod
    def filter_notebooks(cls, items: List):
        remove_items = []
        # Loop over all collected items
        for item in items:
            remove = False
            path = str(item.reportinfo()[0])
            # If we want to skip the notebook, set remove=True
            if path.endswith(".ipynb"):
                cls.num_coll += 1
                remove = any((d in path for d in cls.skip_dirs)) or not path.endswith("_test.ipynb")
            # Add item for removal OR count the notebook
            if remove:
                remove_items.append(item)
            else:
                cls.num_test += 1
        # Remove items
        for item in remove_items:
            items.remove(item)

    @classmethod
    def report(cls) -> List[str]:
        return ["-" * 20,
                "Jupyter Notebooks",
                "-" * 20,
                f"{cls.num_pre:<4d} preprocessed",
                f"{cls.num_coll:<4d} total",
                f"{cls.num_test:<4d} test",
                "-" * 20]


def print_hook(config, s):
    log = NotebookPrep.get_log(config)
    log.info(f"IDAES pytest hook -> {s}")


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config):
    print_hook(config, "pytest_configure")
    NotebookPrep.configure(config)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items: list):
    print_hook(config, "pytest_collection_modifyitems")
    NotebookPrep.filter_notebooks(items)


@pytest.hookimpl(trylast=True)
def pytest_report_collectionfinish(config, start_path, startdir, items):
    print_hook(config, "pytest_report_collectionfinish")
    return NotebookPrep.report()
