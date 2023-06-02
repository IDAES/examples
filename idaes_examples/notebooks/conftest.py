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
import time


logging.basicConfig()


def is_master():
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw?")
    return worker == "gw0"


class NotebookPrep:
    """Simple wrapper for notebook pre-processing state and operations."""

    worker_logs = {}

    num_pre = 0
    num_test = 0
    num_coll = 0

    skip_dirs = [f"{p}{os.path.sep}" for p in ("archive", "_dev")]

    @classmethod
    def get_logfile_name(cls, worker_id) -> str:
        return f"tests_{worker_id}.log"

    @classmethod
    def get_log(cls, config=None):
        worker_id = os.environ.get("PYTEST_XDIST_WORKER")
        if worker_id is None:
            log = logging.root
        else:
            try:
                log = cls.worker_logs[worker_id]
            except KeyError:
                level, fmt = None, None
                if config is not None:
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
                    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                log = logging.getLogger(f"pytest_worker_{worker_id}")
                log.setLevel(level)
                logname = cls.get_logfile_name(worker_id)
                Path(logname).unlink(True)
                h = logging.FileHandler(logname)
                h.setFormatter(logging.Formatter(fmt))
                log.addHandler(h)
                cls.worker_logs[worker_id] = log
        return log

    @classmethod
    def configure(cls, config: pytest.Config):
        """Run preprocessing before tests.

        For pytest-xdist, this needs to run once (on the 'master'), with all
        other workers waiting for the preprocessing to complete. To achieve this
        simply, we create a lockfile in the current directory.
        """
        log = cls.get_log(config)
        lock_file_name = "pytest_pre.lock"
        if is_master():
            Path(lock_file_name).unlink(True)
            p = config.rootpath
            log.info(f"Preprocessing Jupyter notebooks in {p}")
            cls.num_pre = build.preprocess(p)
            if cls.num_pre == 0:
                raise RuntimeError(
                    f"Error in preprocessing of Jupyter notebooks: no notebooks found"
                )
            # Write a marker file to indicate preprocessing is done
            with open(lock_file_name, "w") as f:
                pass
        else:
            start_time = time.time()
            count, max_count = 1, 10
            while count <= max_count:
                log.info(
                    f"({count}) Wait for preprocessing (lockfile={lock_file_name})"
                )
                time.sleep(1)
                # Look for lockfile that is relatively recent (ignore stale ones)
                p = Path(lock_file_name)
                if p.exists() and p.stat().st_ctime < start_time + 60:
                    log.info(f"Preprocessing is complete")
                    break
                # If no recent lockfile found, loop
                count += 1
            if count > max_count:
                end_time = time.time()
                duration = int(round(end_time - start_time))
                raise RuntimeError(
                    f"Preprocessing not completed in {duration} seconds. "
                    f"Check logs of 'master' process: {cls.get_logfile_name('gw0')}"
                )

    @classmethod
    def filter_notebooks(cls, items: List):
        """Modify input list of pytest items in-place to remove Jupyter notebooks that
        are not in a testing directory or which are not test notebooks.
        """
        remove_items = []
        # Find items to remove in all items
        for item in items:
            remove = False
            path = str(item.reportinfo()[0])
            # Set remove=True for certain Jupyter notebooks
            if path.endswith(".ipynb"):
                cls.num_coll += 1
                # Remove if directory we should skip OR not a test notebook
                remove = any((d in path for d in cls.skip_dirs)) or not path.endswith(
                    "_test.ipynb"
                )
            # Process result: Add item for removal OR count the notebook
            if remove:
                remove_items.append(item)
            else:
                cls.num_test += 1
        # Remove found items
        for item in remove_items:
            items.remove(item)

    @classmethod
    def report(cls) -> List[str]:
        cls.get_log().info(
            f"Jupyter notebooks: {cls.num_pre} preprocessed, {cls.num_coll} total,"
            f" {cls.num_test} test"
        )
        return [
            "-" * 20,
            "Jupyter Notebooks",
            "-" * 20,
            f"{cls.num_pre:<4d} preprocessed",
            f"{cls.num_coll:<4d} total",
            f"{cls.num_test:<4d} test",
            "-" * 20,
        ]


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
