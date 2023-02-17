# IDAES Examples

This repository contains example Jupyter Notebooks that demonstrate and  explain 
the  capabilities of the IDAES platform.

Below are basic instructions to install, view, and run the examples.

If you are a developer who wishes to modify or add new notebooks, please refer to the file *README-developer.md*.

### Categories of examples

In the source code repository, you may note that there are a number of examples that are not in the documentation.
Overall, there are three categories of examples:

  - "Docs" examples (under `idaes_examples/notebooks/docs`), which are tested and built into this documentation.
  - "Active" examples (under `idaes_examples/notebooks/active`) that *are* tested against the current version of IDAES.
  - "Archived" examples (under `idaes_examples/archive`) that are no longer tested against the current version of 
    IDAES.

## Installation

This repository can be installed with *pip*:
```shell
pip install idaes-examples
```

We recommend you use a virtual environment tool such as
[Miniconda](https://docs.conda.io/en/latest/miniconda.html)
to install and run the notebooks in an isolated environment.

## Run examples

Use the command `idaesx gui` to get a simple graphical UI that lets you 
browse and open notebooks for local execution and experimentation.

## Build documentation

Run the command `idaesx build` from the repository root to build the [JupyterBook](https://jupyterbook.org) 
documentation.


*Note: This will take quite a while, as each example must be run first.
You may want to step out and enjoy a beverage.*


----
Author: Dan Gunter  
Last modified: 17 Feb 2023