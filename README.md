<!-- Badges -->
[![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/lbianchi-lbl/examples/binder?labpath=idaes_examples%2Fnotebooks%2Fdocs)
[![tests](https://github.com/IDAES/examples/actions/workflows/core.yml/badge.svg)](https://github.com/IDAES/examples/actions/workflows/core.yml)
&nbsp;
[![Documentation](https://readthedocs.org/projects/idaes-examples/badge/?version=latest)](https://idaes-examples.readthedocs.io/en/latest/?badge=latest)

# IDAES Examples

This repository contains example Jupyter Notebooks that demonstrate and  explain 
the  capabilities of the IDAES platform.

Below are basic instructions to install, view, and run the examples.

**For Developers**: If you are a developer who wishes to modify or add new notebooks, please refer to the file *README-developer.md*.

**Categories of examples**

In the source code repository, you may note that there are a number of examples that are not in the documentation.
There are two main categories of examples:

- "Docs" examples (under `idaes_examples/notebooks/docs`), which are tested and built into this documentation.
- "Active" examples (under `idaes_examples/notebooks/active`) that are tested but *not* in the documentation.

There is also a third category of "Held" examples (under `idaes_examples/notebooks/held`),
which could in the next release of IDAES in Docs or Active, or could be removed.
These are *not* tested and *not* in the docs, and should generally be ignored by non-developers.

## Installation

This repository can be installed with *pip*:

```shell
# RECOMMENDED: this will install the IDEAS examples, accessory code,
# plus the Graphical User Interface (GUI) to browse them (see section below)
pip install "idaes-examples[gui]"
```

We recommend you use a virtual environment tool such as
[Miniconda](https://docs.conda.io/en/latest/miniconda.html)
to install and run the notebooks in an isolated environment.

## Run examples

Use the command
```
idaesx serve
```
to start a Jupyter server to browser and open the notebooks for local execution and experimentation.

Alternately, you may use Jupyter notebook's file browser in the installed notebooks directory,
using the `idaesx where` command to find that directory:
`jupyter notebook $(idaesx where)`.

Only the source notebooks (ending in `_src.ipynb`) are included in the repository.
The `idaesx serve` command will generate the other versions, or you can run preprocessing manually with: `idaesx pre -d "$(idaesx where)\.."`.

## Build documentation

Run the command `idaesx build` from the repository root to build the [JupyterBook](https://jupyterbook.org) 
documentation.

*Note: This will take quite a while, as each example must be run first.
You may want to step out and enjoy a beverage.*

----
Author: Dan Gunter  
Last modified: 25 Apr 2024
