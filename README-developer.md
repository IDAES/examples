# Developer README

This file provides details needed by developers to properly create and add new example notebooks to this repository.

**Table of Contents**
* Installation
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

## Installation

Clone the repository from Github, setup your Python environment as you usually do, then run pip with the developer requirements:

```shell
# to create a conda environment first:
# conda create -n idaes-examples python=3; conda activate idaes-examples
pip install -e .[dev]
```

The configuration of the installation is stored in `pyproject.toml`.
 
## File layout

This section describes the internal organization of the example notebooks and supporting files.

### Directories
The examples are divided into a few top-level directories.

* `notebooks`: All the active/tested Jupyter notebooks and supporting data
  * `docs`: Examples and tutorials that will be tested and also published in the online documentation.
  * `active`: Not published but tested against new PRs
  * `_dev`: Notebooks used as examples for development and testing only.
* `archive`: Not published and *not* tested. Just for historical interest.
* `mod`: Supporting Python modules (as a Python package).  
  It is usually best to match the name of the Python subpackage with its notebook directory.

### Where to put a new notebook

Use the following to decide where to put any new Jupyter notebook:

1. Will it be included in the online docs?  
**Yes**: Put under `notebooks/docs`  
**No**: Go to 2
2. Will it be actively maintained to handle any changes in IDAES core?  
**Yes**: Put under `notebooks/active`  
**No**: Put under `archive`

All these directories have their own subdirectories for grouping similar notebooks.
Place the new notebook in an appropriate subdirectory.

Data files and images should go in the same directory as the notebook.  
Python modules should go under an appropriate subpackage under `mod`.

## Running tests

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

The commands to run tests and build documentation both run a preprocessing step that creates separate copies of the Jupyter notebooks that are used for tests, tutorial exercise and solution, and documentation (see Notebook Names).
These generated files should ***not*** be added to the repository.
If you want to run that preprocessing step separately, use `idaesx pre`.
To remove pre-processed files, run `idaesx clean`.

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

Notebooks all have a file name that fits the pattern notebook-name`_ext`.ipynb*.
When creating or modifying notebooks, you should always use `ext` = *src*.
Other extensions are automatically generated when running tests, building the documentation, and manually running the preprocessing step.
See the <a href="#table-nbtypes">table of notebook types</a> for details.

## How to add a new notebook

See `tutorial.md` in this directory for a more detailed step-by-step tutorial.

There are two main steps to creating a new notebook example.

1. Add Jupyter Notebook and supporting files
   1. Look at the `README.md` file in *idaes_examples* to figure out where to put the notebook.
   2. If you create a new directory for the notebook, the directory name *should* be in lowercase 
      with underscores between words. For example: 'machine_learning'.
   3. Notebook filename *should* be in lowercase with underscores and ***must*** end with '_src.ipynb'. For example: 
      'my_example_src.ipynb'.
   4. Add -- in the same directory as the notebook -- any data files or images it needs.
   5. Additional Python modules should be put in an appropriate place under *idaes_examples/mod*.
Then your notebook can write: `from idaes_examples.mod.<subpackage> import <bla>`
2. Add Jupyter notebook to the Jupyterbook table of contents in *idaes_examples/nb/_toc.yml*.
   1. The notebook will be a *section*. If you added a new directory, you will create a new *chapter*, otherwise it will go under an existing one. See [Jupyterbook][jb] documentation for more details.
   2. Refer to the notebook as '*path/to/notebook-name*_doc' (replace '_src' with '_doc' and drop the '.ipynb' extension). For example: 'machine_learning/my_example_doc'.
   3. If you created a new directory for this notebook, make sure you add an *index.md* file to it. See other *index.md* files for the expected format.

You *should*  test the new notebook and build it locally before pushing the new file, i.e., run `pytest` and `idaesx build`.

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


<!-- 
   References 
-->
[jb]: https://jupyterbook.org/
[hidecell]: https://jupyterbook.org/en/stable/interactive/hiding.html
[celltags]: https://jupyterbook.org/en/stable/content/metadata.html

----
Author: Dan Gunter  
Last modified: 03 Feb 2023