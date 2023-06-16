"""
Utility functions for IDAES examples
"""
# stdlib
import contextlib
import logging
import re
from typing import Optional

# pkg
from idaes.core.solvers import get_solver as idaes_get_solver

__author__ = "Dan Gunter"


def get_solver(*args, **kwargs):
    """Replacement for `idaes.core.solvers.get_solver` that returns a solver
    that suppresses some log output (see :class:`SuppressSolverLogs`).

    This allows suppression of log output by simply changing imports::

        from idaes.core.solvers import get_solver       # OLD
        from idaes_examples.mod.util import get_solver  # NEW

    This is mostly intended for interactive contexts.
    """
    return _SolverWrapper(*args, **kwargs)


class _SolverWrapper:
    """Used by :func:`get_solver` to wrap the IDAES solver object."""
    def __init__(self, solver=None, options=None):
        self._idaes_solver = idaes_get_solver(solver=solver, options=options)

    def solve(self, *args, **kwargs):
        with SuppressSolverLogs():
            self._idaes_solver.solve(*args, **kwargs)


class SolverLogFilter(logging.Filter):
    """Filter solver logs with `logging.Filter`s.

    The main feature of this filter is that it is abo
    """
    def __init__(self, logger_name: str,
                 filters: Optional[dict[str, re.Pattern | str]] = None,
                 report_level: Optional[int] = None,
                 handlers: bool = False):
        """Create a filter for given named logger in the hierarchy.

        Args:
            logger_name: name of logger to filter messages from
            filters: Filters to add:
                - key is descriptive text (printed at end) of the thing being filtered
                - value is a regular expression to match against the log message,
                  either as a string or a compiled Pattern object
            report_level: If not None, logging level for reporting at end
            handlers: If True, apply filter to handlers of logger, otherwise add the
                filter to the logger object itself.
        """
        super().__init__(self.__class__.__name__)
        self.saved = None if report_level is None else []
        self._lvl = report_level
        self.logger = logging.getLogger(logger_name)
        # pre-process to convert strings to regex patterns
        self.filter_exprs = {k: (v if isinstance(v, re.Pattern) else re.compile(v))
                             for k, v in filters.items()}
        self._hnd = handlers

    def start(self):
        if self._hnd:
            for hnd in self.logger.handlers:
                hnd.addFilter(self)
        else:
            self.logger.addFilter(self)

    def filter(self, record: logging.LogRecord) -> bool:
        """Called by Python logging framework for each record."""
        for name, regex in self.filter_exprs.items():
            if regex.search(record.msg):
                if self.saved is not None:
                    self.saved.append((name, record))
                return False
        return True

    def done(self):
        """Called by context manager on exit."""
        if self.saved:
            # group into {warning_type: count}
            groups = {}
            for warning_type, rec in self.saved:
                if warning_type not in groups:
                    groups[warning_type] = 0
                groups[warning_type] += 1
            # report each group
            for warning_type, count in groups.items():
                self.logger.log(
                    self._lvl,
                    f"{count} from {self.logger.name}: {warning_type}",
                )
            self.saved = []
        # reset
        if self._hnd:
            for hnd in self.logger.handlers:
                hnd.removeFilter(self)
        else:
            self.logger.removeFilter(self)


class FilterLogs(contextlib.AbstractContextManager):
    """Base class for filtering log messages with a context manager."""

    def __init__(self, args: list[SolverLogFilter]):
        """Constructor.

        Args:
            args: Initial set of log filters.
        """
        self.filters = args

    def __enter__(self):
        try:
            for f in self.filters:
                f.start()
        finally:
            return self

    def __exit__(self, *args):
        try:
            for f in self.filters:
                f.done()
        finally:
            pass


class SuppressSolverLogs(FilterLogs):
    """Context manager to suppress logged warnings while running a solver.

    Example usage::

        with SuppressSolverLogs():
            solvers.solve(model, ...)

    You can add custom filters by adding one or more SolverLogFilter instances
    in the positional constructor args. You could also create a subclass of
    this class or the base :class:`FilterLogs` to create your own context manager
    that does whatever filtering you want.
    """
    def __init__(self, *args,
                 pyomo_warnings: bool = True,
                 idaes_init_messages: bool = True):
        """Constructor.

        Args:
            *args: Additional :class:`SolverLogFilter` instances.
            pyomo_warnings: If true, filter uot Pyomo warnings about not exporting
                suffixes for component keys.
            idaes_init_messages: If true, filter out informational messages about
                IDAES initialization
        """
        super().__init__(list(args))
        # add nl_writer filter
        if pyomo_warnings:
            self.filters.append(
                SolverLogFilter("pyomo.repn.plugins.nl_writer", {
                    "model export suffix not exported to NL file": re.compile(
                        r"export suffix.*component keys.*not exported")
                }, report_level=logging.WARNING))
        # add filter for uninteresting init messages
        if idaes_init_messages:
            self.filters.append(
                SolverLogFilter("idaes.init", {
                    "property/model initialization": re.compile(
                        r"starting initialization|"
                        r"property( package)? initialization|"
                        r"initialization complete",
                        flags=re.IGNORECASE)
                }, report_level=logging.INFO, handlers=True))

