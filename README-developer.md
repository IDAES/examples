# Developer README

This file provides details needed by developers to properly create and add new example notebooks to this repository.

**Contents:**

* [Installation](#installation)
* [How to add a new notebook example](#how-to-add-a-new-notebook-example)
* [File layout](#file-layout)
* [Running tests](#running-tests)
* [Building and preprocessing](#building-and-preprocessing)
* [Notebook names](#notebook-names)
* [Copyright headers](#copyright-headers)
* [Packaging for PyPI](#packaging-for-pypi)

## Installation

Clone the repository from GitHub, set up your Python environment as you usually do, then run pip with the developer requirements:

```shell
# to create a conda environment first:
# conda create --yes --name idaes-examples python=3.10 && conda activate idaes-examples
pip install -r requirements-dev.txt
```

Note: if you have IDAES installed in your current environment, it will uninstall it and install the latest version from the main branch on Github. You can run `pip uninstall idaes-pse` and reinstall it from your local repository if you need to test examples against a local branch of IDAES.

The configuration of the installation is stored in `pyproject.toml`.

## How to add a new notebook example

Examples are currently all [Jupyter](https://jupyter.org) Notebooks. This section goes through the main steps to creating a new notebook example. For more details about naming and layout, see the reference sections on [File layout](#file-layout) and [Notebook names](#notebook-names), below. In particular, it is recommended to read the section on [Jupyter Notebook cell tags](#jupyter-notebook-cell-tags), found under the Notebook names section; these are used for testing, to handle the "solution" cells in a tutorial, etc.

First, pick the directory in which to add the notebook. See the [standards][standards] to figure out the parent directory for the notebook -- usually, it's *notebooks/docs*. The examples are organized into sections. This affects how the notebook will appear in the overall navigation of the documentation when it is published.

Next, you need to choose whether to put your new notebook in an existing section or to create a new section. 

- Use existing section: Simply navigate there before the next step. 

- Create a new section: in `notebooks/docs` or `notebooks/held`, create a new subdirectory. The directory name *should* be in lowercase with underscores between words. Also create and populate an *index.md* file, e.g.,  `notebooks/docs/fantastic/index.md` file. This should describe the section and notebooks in it.

Next, choose to use the *idaesx new* command to create a new blank notebook or to copy/edit an existing notebook yourself. In either case, the notebook filename should be in lowercase with underscores. For example: *my_notebook*.

- If you are adding your notebook using the `idaesx new` command, you need to just pick a section and name for the notebook. The script will modify the `notebooks/_toc.yml` and create a blank notebook to get started.
- If you are adding your notebook manually, copy or create the notebook file, e.g., `notebooks/docs/fantastic/my_notebook.ipynb`. Make sure you add the *.ipynb* extension. You also need to add a "file" entry in `notebooks/_toc.yml` , as a new item in the list under the appropriate section, with "_doc" appended to the name and without the extension, e.g. `- file: docs/fantastic/my_notebook_doc`. 

If the new notebook needs any data files or images, add these in the same directory as the notebook. Remember to add these to Git as well.

If your new notebook needs additional Python modules, these should be put under the `mod/` directory in an appropriate place, usually a directory name that matches the notebook's subdirectory under `docs/`. For example, our notebook in `notebooks/docs/fantastic/my_notebook.ipynb` could have an additional module  `mod/fantastic/util.py`, which will be imported: `from idaes_examples.mod.fantastic import util`. 

Finally, you will test the new notebook and build it locally before adding, committing, and pushing the new files. See the section on [running tests](#running-tests), below. 

## File layout

This section describes the internal organization of the example notebooks and supporting files.

### Directories
The examples are divided into a few top-level directories.

* `notebooks`: All the active/tested Jupyter notebooks and supporting data
  * `docs`: Examples and tutorials that will be tested and also published in the online documentation.
  * `active`: Not published but tested against new PRs
  * `_dev`: Notebooks used as examples for development and testing only.
  * `held`: Not published and *not* tested. For the next release (or removal).
* `mod`: Supporting Python modules (as a Python package).  
  It is usually best to match the name of the Python subpackage with its notebook directory.

For guidance on where to put a new notebook, see the [Examples Standards][standards] page in the IDAES examples repo wiki.

## Running tests

There are two sets of tests in this repo.
Which one you run depends in which directory you run tests.

If your current directory is the root of the repository:

1. `pytest .`: Runs **Python test modules**, matching the usual patterns (e.g., `test_*.py`).
2. `pytest idaes_examples`: Runs **Jupyter notebook tests.** Due to the presence of a special `conftest.py` file in this directory, Jupyter Notebooks will be preprocessed and then all test notebooks (their filename ending in `_test.ipynb`) will be executed.

The `-v` or `--verbose` flag can be added to any pytest command so that more information is displayed while the test suite runs.

### Testing the notebooks

To run all registered notebooks, run the following command from the top-level (root) directory of the repository, specifying `idaes_examples` as an argument.
The `pytest.ini` file and `conftest.py` files contained in `idaes_examples` will override the top-level pytest configuration defined in `pyproject.toml` under `[tool.pytest.ini_options]`.

```shell
# from the root directory of the repository
pytest idaes_examples
```

#### Testing a subset of the notebooks

To test just one notebook, you need to use the name of the *test* notebook not the source.
For example, to test the `compressor.ipynb` notebook (in the `unit_models/operations` subdirectory)
you need to use the name of the test notebook:

```shell
pytest -v idaes_examples/notebooks/docs/unit_models/operations/compressor_test.ipynb
```

If you want to test several related notebooks, or perhaps just not type the whole notebook filename,
you can use the pytest `-k` flag to test all notebooks whose path matches a string (see pytest docs for details).
So, for example, from the top-level directory if you want to test all the *docs/unit_models/operations* notebooks,
you could take advantage of the fact that "operations" appears only in this particular path:

```shell
pytest -v idaes_examples -k operations
# will match: 
# docs/unit_models/operations/compressor_test.ipynb
# docs/unit_models/operations/heat_exchanger_0d_test.ipynb
# docs/unit_models/operations/mixer_test.ipynb
# docs/unit_models/operations/heater_test.ipynb
# docs/unit_models/operations/skeleton_unit_test.ipynb
# docs/unit_models/operations/pump_test.ipynb
# docs/unit_models/operations/turbine_test.ipynb
```

## Building and preprocessing

### Building documentation

**Note:** Building the documentation runs all the notebooks.
This is very slow, so is not an operation that a developer should perform during their regular workflow. 
Notebooks should be written with *unit tests* (see above) that can be run quickly to check correctness and syntax during creation and debugging.

The documentation is built using [Jupyterbook][jb].
We have written a thin layer around the Jupyterbook executable, which is installed as a command-line program *idaesx*.
To build the documentation, run:

```shell
idaesx build
```

The output will be in *idaes_examples/nb/_build/html*. As a convenience, you can open that HTML file with the command `idaesx view`.

### Preprocessing notebooks
Preprocessing creates separate copies of the Jupyter notebooks that are used for tests, tutorial exercise and solution, and documentation (see [Notebook Names](#notebook-names)).
These (derived) notebooks are also committed and saved in Git.

To re-run the preprocessing, which will update any derived files that are
out of date (older than the corresponding `*.ipynb` file):
```shell
idaesx pre
```

A diagram of how preprocessing relates to notebook usage is shown below:

```
 ┌───────────────┐
 │               │
 │ example.ipynb │
 │               │
 └──────┬────────┘
        │
        ▼            ┌──────────────────┐     ┌──────┐
 ┌────────────┐  ┌─► │example_test.ipynb├────►│pytest│
 │ preprocess ├──┤   └──────────────────┘     └──────┘
 └──────────┬─┘  │
            │    │   ┌─────────────────┐      ┌───────────┐
            │    └─► │example_doc.ipynb├─────►│jupyterbook│
            │        └─────────────────┘      └───────────┘
            │
            │        ┌─────────────────┐     ┌───────────┐
           ┌┴─┐  ┌──►│example_usr.ipynb├────►│ browse/run│
           │OR├──┤   └─────────────────┘     └───────────┘
           └──┘  │                                ▲
                 │   ┌──────────────────────┐     │
                 │   │example_exercise.ipynb├─────┘
                 └──►│example_solution.ipynb│
                     └──────────────────────┘
```

<a name="notebook-names"></a>

## Notebook names

Notebooks all have a file name that fits the pattern notebook-name`_<ext>`.ipynb*.
When creating or modifying notebooks, you should always use the version with no extension, i.e. *.ipynb.
Other extensions are automatically generated when running tests, building the documentation, and manually running the preprocessing step.
See the <a href="#table-nbtypes">table of notebook types</a> for details.



### Jupyter Notebook file extensions

Each source Jupyter notebook (ending in '.ipynb') is preprocessed to create additional notebooks which are a copy of the original with some cells (steps in the notebook execution) removed.

<a name="table-nbtypes"></a>

| Notebook type | Description                | Ends with       |
| ------------- | -------------------------- | --------------- |
| source        | Notebook source            | .ipynb          |
| testing       | Run for testing            | _test.ipynb     |
| exercise      | Tutorial exercises only    | _exercise.ipynb |
| solution      | Tutorial ex. and solutions | _solution.ipynb |
| documentation | Show in documentation      | _doc.ipynb      |
| user          | Run by end-users           | _usr.ipynb      |

### Jupyter Notebook header

Every notebook *must* have a copyright header as its first cell (see the section 
"Copyright headers"). The cell immediately after the copyright header *must* be another 
markdown cell that follows this format:

```markdown
# Title of notebook
Author: Author Name
Maintainer: Maintainer Name
Updated: YYYY-MM-DD

Description of what this notebook does.
```

For example,
```markdown
# NGCC Baseline and Turndown
Author: John Eslick
Maintainer: John Eslick
Updated: 2023-06-01

This notebook runs a series of net electric power outputs from 650 MW to 160 MW
(about 100% to 25%) for an NGCC with 97% CO2 capture. The NGCC model is based on 
the NETL report "Cost and Performance Baseline for Fossil Energy Plants Volume 1: 
Bituminous Coal and Natural Gas to Electricity." Sept 2019, Case B31B 
(https://www.netl.doe.gov/projects/files/CostAndPerformanceBaselineForFossilEnergyPlantsVol1BitumCoalAndNGtoElectBBRRev4-1_092419.pdf).
```

To be clear, there *must* be some cell that has this format in the notebook, but
it doesn't have to come right after the copyright, e.g. if you want to
have a logo or some vacation photos first you can do that. But it must be present as
its own cell.

There is a test in `idaes_examples.tests.test_notebooks` called `test_headers()`
that will enforce the requirement that all notebooks have an author and maintainer
field as shown above.

You can print all headers or add specific headers with the `idaesx hdr` command.
See `idaes hdr --help` for more details.

The utility code to parse the headers is called by and adjacent to the 
`idaes_examples.build` module's `print_header()` function.

### Jupyter Notebook cell tags

Preprocessing uses the feature of Jupyter notebook [cell tags][celltags] to understand which additional notebooks to 
create.

The following tags are understood by the preprocessing step:

<a name="table-nbtags"></a>

* testing: Remove this cell, except in the *testing* notebooks
* exercise: The presence of this tag means a notebook is a tutorial.
    Generate an _exercise_ and _solution_ notebook, and keep this cell in both. Remove this cell in the _documentation_ notebook.
* solution: The presence of this tag means a notebook is a tutorial.
    Generate an _exercise_ and _solution_ notebook, but remove this cell in the *solution* notebook; keep the cell in the _documentation_ notebook.
* noauto: This tag means that this cell should not be run during automated 
    notebook execution. The cell will be removed in _testing_ and _documentation_ notebooks.
* auto: This tag means that this cell should **only** be run during automated 
    notebook execution. The cell will be removed in all notebooks **except** _testing_ and _documentation_.         

All other tags, including the standard [Jupyterbook tags][hidecell] for hiding or removing cells, will be ignored.

#### Cell tags tutorial

An example of these tags, with a tutorial on how to set them, is in the `_dev/notebooks/ex/notebook_tags_example.
ipynb` 
notebook. In this directory the pre-processed output notebooks have been added to Git so you can see what they look 
like (without having to run `idaesx pre` yourself).

You can see the results by building the development notebooks into a documentation tree with `idaesx build 
--dev` (from the same directory you would normally run).
The output will be in `_dev/notebooks/_build/html`.

### Jupyter notebook metadata

In addition to per-cell tags, the preprocessor also can look at notebook-level metadata.
This is currently used for only one purpose: to tell the preprocessor not to generate a 'test' notebook, and thereby to skip the given notebook in the tests.
In order to make this happen, either manually edit the notebook source or use the Jupyter notebook "Edit -> Edit Notebook Metadata" menu item to add the following section to the notebook-level metadata:

```json
"idaes": {
   "skip": ["test"]
}
```

## Copyright headers

You can add (and update) copyright headers to Python files _and_ Jupyter Notebooks using the 
`addheader` command with the included `addheader.yml` configuration file:

```bash
# first see what would be changed (using -n)
addheader -n -c addheader.yml
# if this is OK, add the headers
addheader -c addheader.yml
```

All existing notebooks and Python files will be automatically discovered and modified as needed.

## Packaging for PyPI

Instructions to package and distribute the examples as idaes-examples in PyPI.
Based on the PyPA [packaging projects](https://packaging.python.org/en/latest/tutorials/packaging-projects/)  documentation.

Install dependencies for packaging into your current (virtual) Python environment:

```shell
pip install -e .[dev,packaging]
```

Edit the `pyproject.toml` file:

1. Ensure that you have commented out the line under `[project.optional-dependencies]`, in the `dev` section,
     that reads `"idaes-pse @ git+https://github.com/IDAES/idaes-pse"`.
2. Set the release version.  You should increment the version for each new release.

**Build** the distribution:

```shell
> python -m build
# Many lines of output later, you should see a message like:
Successfully built idaes_examples-x.y.z.tar.gz and idaes_examples-x.y.z-py3-none-any.whl
```

If you have not already done so, create an account on [testpypi](https://test.pypi.org).

Copy your API token from your account.
To generate an API token, go to _Settings_ &rarr; _API Tokens_, and selecting _Add API Token_.
You will paste this token in the commands below.

**Upload** to [TestPyPI](https://packaging.python.org/en/latest/guides/using-testpypi/):

```shell
> python -m twine upload --repository testpypi dist/*
Uploading distributions to https://test.pypi.org/legacy/
Enter your username: __token__
Enter your password: {{paste token here}}
```

Create a new virtual environment and install the package from test.pypi into it:

```shell
pip install --extra-index-url https://test.pypi.org/simple/ idaes-examples
```

If the installation succeeds, you should be able to serve the notebooks:

```shell
idaesx serve
```

If it all looks good, you can repeat the **Upload** step with the real [PyPI](pypi.org) 
(you will need to get an account and token, just as for test.pypi.org, above):

```shell
> python -m twine upload dist/*
Uploading distributions to https://upload.pypi.org/legacy/
Enter your username: __token__
Enter your password: {{past token here}}
```

<!-- 
   References 
-->
[jb]: https://jupyterbook.org/
[hidecell]: https://jupyterbook.org/en/stable/interactive/hiding.html
[celltags]: https://jupyterbook.org/en/stable/content/metadata.html
[standards]: https://github.com/IDAES/examples/wiki/IDAES-Examples-Standards

----
Author: Dan Gunter  
Last modified: 25 Apr 2024
