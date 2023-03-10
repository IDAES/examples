# Dynamic Modeling: Differential-Algebraic Equations

These examples provide an overview of the PETSc time-stepping solver utilities in IDAES, which can be used to solve systems of differential algebraic equations (DAEs).
[PETSc][petsc] is a solver suite developed primarily by Argonne National Lab.
IDAES provides a [wrapper for PETSc][petsc-wrapper] that uses the [AMPL solver interface][ampl] and utility functions that allow Pyomo and [Pyomo.DAE][pyomo-dae] problems to be solved using PETSc.

[petsc]: https://petsc.org/release/
[petsc-wrapper]: https://github.com/IDAES/idaes-ext/tree/main/petsc
[ampl]: https://ampl.com/resources/learn-more/hooking-your-solver-to-ampl/
[pyomo-dae]: https://pyomo.readthedocs.io/en/stable/modeling_extensions/dae.html