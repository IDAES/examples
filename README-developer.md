# Developer README

This file provides details needed by developers to properly create and add new example notebooks to this repository.

**Table of Contents**
* Installation
* Add a new example
* File layout
* Running tests
* Building documentation
* Preprocessing
* Copyright headers
* Notebook names
* How to create an example
  * Jupyter Notebook file extensions
  * Jupyter Notebook cell tags
  * Jupyter notebook metadata
* Packaging

**Quickstart**, skip to sections:
* [Installation](#installation)
* [Running tests &rarr; Integration tests](#integration-tests)
* [Building documentation](#building-documentation)


**Quickstart**, skip to sections:
* [Installation](#installation)
* [Add a new example](#add-a-new-example)
* [Running tests &rarr; Integration tests](#integration-tests)
* [Building documentation](#building-documentation)


## Installation

Clone the repository from GitHub, set up your Python environment as you usually do, then run pip with the developer requirements:

```shell
# to create a conda environment first:
# conda create -n idaes-examples python=3; conda activate idaes-examples
pip install -e .[dev,jb]
```

The configuration of the installation is stored in `pyproject.toml`.

## Add a new example

Note: Below, `notebooks/*` refers to the directory `idaes_examples/notebooks`.

If you want to add an example in an **existing section** of `notebooks/docs`, you can run
`idaesx new` to get a guided terminal-based UI that will create a skeleton of the
new notebook and add it to the table of contents. Then you just need to edit your
notebook.

If you need to create a **new section** in `notebooks/docs` or `notebooks/held`:
- add the appropriate subdirectory, e.g. `notebooks/docs/fantastic`
- add a section into `notebooks/_toc.yml`, imitating an existing entry
- create and populate a `notebooks/docs/fantastic/index.md` file
- now you can add your notebook(s) manually, e.g. `notebooks/docs/fantastic/my_notebook_src.ipynb`, or use the `idaesx new` command

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

1. `pytest .`: Runs **Python test modules**, matching the usual patterns (e.g., `*_test.py`).
2. `pytest idaes_examples`: Runs **Jupyter notebook tests.** Due to the presence of a special `conftest.py` file in this directory, Jupyter Notebooks will be preprocessed and then all test notebooks (their filename ending in `_test.ipynb`) will be executed.

### Integration tests

Run integration tests from the top-level (root) directory of the repository.
In the root directory, tests are configured by `pyproject.toml`; see the *tool.pytest.ini_options* section.

```shell
# from the root directory of the repository
pytest idaes_examples
```

#### Testing a subset of the notebooks

To test just one notebook, you need to use the name of the *test* notebook not the source.
For example, to test the `compressor_src.ipynb` notebook (in the `unit_models/operations` subdirectory)
you need to add `-c` and the path to the top-level *pyproject.toml*, which has the pytest configuration,
then use the name of the test notebook:

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

## Building documentation

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

## Preprocessing notebooks
Preprocessing creates separate copies of the Jupyter notebooks that are used for tests, tutorial exercise and solution, and documentation (see Notebook Names).
These (derived) notebooks are also committed and saved in Git.

To re-run the preprocessing, which will update any derived files that are
out of date (older than the corresponding `*_src.ipynb` file):
```shell
idaesx pre
```

A diagram of how preprocessing relates to notebook usage is shown below:

```
 ┌───────────────────┐
 │                   │
 │ example_src.ipynb │
 │                   │
 └──────┬────────────┘
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

## Notebook names

Notebooks all have a file name that fits the pattern notebook-name`_<ext>`.ipynb*.
When creating or modifying notebooks, you should always use `<ext>` = *src*.
Other extensions are automatically generated when running tests, building the documentation, and manually running the preprocessing step.
See the <a href="#table-nbtypes">table of notebook types</a> for details.

## How to add a new notebook

There are two main steps to creating a new notebook example.

1. Add Jupyter Notebook and supporting files
   1. See the [standards][standards] to figure out the parent directory for the notebook -- usually, it's *docs*.
   2. Put the notebook in the appropriate subdirectory.
      If you create a new directory for the notebook, the directory name *should* be in lowercase 
      with underscores between words. For example: '*docs/machine_learning*'.
   3. Notebook filename *should* be in lowercase with underscores and ***must*** end with '_src.ipynb'. For example: 
      'my_example_src.ipynb'.
   4. Add -- in the same directory as the notebook -- any data files or images it needs.
   5. Additional Python modules should be put in an appropriate place under *idaes_examples/mod*.
      Then your notebook can write: `from idaes_examples.mod.<subpackage> import <bla>`
2. Add Jupyter notebook to the Jupyterbook table of contents in *idaes_examples/notebooks/_toc.yml*.
   1. The notebook will be a *section*. If you added a new directory, you will create a new *chapter*, otherwise it will go under an existing one. See [Jupyterbook][jb] documentation for more details.
   2. Refer to the notebook as '*path/to/notebook-name*_doc' (replace '_src' with '_doc' and drop the '.ipynb' extension). For example: 'machine_learning/my_example_doc'.
   3. If you created a new directory for this notebook, make sure you add an *index.md* file to it. See other *index.md* files for the expected format.

You *should*  test the new notebook and build it locally before pushing the new file, i.e., run `pytest` and `idaesx build`.
Note that the cache for the documentation will be updated to contain the new output cells, which will modify files in *idaes_examples/notebooks/nbcache*; these files should also be committed and pushed.

### Jupyter Notebook file extensions

Each source Jupyter notebook (ending in '_src.ipynb') is preprocessed to create additional notebooks which are a copy of the original with some cells (steps in the notebook execution) removed.

<a name="table-nbtypes"></a>

| Notebook type | Description                | Ends with       |
| ------------- | -------------------------- | --------------- |
| source        | Notebook source            | _src.ipynb      |
| testing       | Run for testing            | _test.ipynb     |
| exercise      | Tutorial exercises only    | _exercise.ipynb |
| solution      | Tutorial ex. and solutions | _solution.ipynb |
| documentation | Show in documentation      | _doc.ipynb      |
| user          | Run by end-users           | _usr.ipynb      |

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

An example of these tags, with a tutorial on how to set them, is in the `_dev/notebooks/ex/notebook_tags_example_src.
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
```
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

## Packaging

Instructions to package and distribute the examples as idaes-examples in PyPI.
Based on the PyPA [packaging projects](https://packaging.python.org/en/latest/tutorials/packaging-projects/)  documentation.

Install dependencies for packaging into your current (virtual) Python environment:
```shell
pip install -e .[dev,jb,pkg]
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

If the installation succeeds, you should be able to browse the notebooks using the built-in GUI:
```shell
idaesx gui
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
Last modified: 13 Mar 2023