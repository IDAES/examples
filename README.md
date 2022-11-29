# IDAES Examples

**Table of Contents**

* For Users
  * Install
  * Browse notebooks
  * Build documentation locally
  * Run tests
* For Developers
  * Install
  * Run tests
  * Build documentation
  * Preprocessing
  * Copyright headers
  * Notebook names
  * How to create an example
    * Jupyter Notebook file extensions
    * Jupyter Notebook cell tags
    * Jupyter notebook metadata

This repository contains Jupyter Notebooks (and supporting Python scripts and data) that demonstrate the capabilities of the IDAES platform.

Using the `idaesx` command that comes with this repository, the contained Jupyter Notebooks can be opened and run locally (`idaesx gui`) or built into [Jupyterbook][jb] documentation (`idaesx build`).
The standard Python test runner, `pytest`, can be used to test that all the notebooks execute successfully.

The rest of this README is broken into separate sections for users, to view or run examples, and for developers, who may contribute modifications or new examples to the repository.


----

## For Users

### Install

For now, see the *For Developers* -> *Install* section.

### Browse notebooks

Use the `idaesx gui` command to get a simple graphical UI that lets you browse and open notebooks (in a Jupyter server) for local execution.

### Build documentation locally

Run `idaesx build` from the repository root. For more details, see the *For Developers* -> *Build documentation* section.

### Run tests

Run `pytest` from the repository root.
For more details, see the *For Developers* -> *Run tests* section.

----

## For Developers

This section is intended for people who are creating and modifying examples.
The examples are primarily in Jupyter Notebooks.
Python support files and data may be used to keep the notebooks focused on the interactive material.

### Install

Clone the repository from Github, setup your Python environment as you usually do, then run pip with the developer requirements:

```shell
pip install -r requirements-dev.txt
```

### Run tests

There are two ways to run tests: running all the notebooks (integration tests), and 
testing that notebooks work without running all their code (unit tests).

To run **integration tests**, from the *root* directory:

```shell
# from the root directory of the repository
pytest
```

If you want to *exclude* certain notebooks from the integration tests, see the _Preprocessing -> Jupyter notebook metadata_ section.

To run the **unit tests** change to do the `idaes_examples` directory, then run the same command:

```shell
cd idaes_examples
pytest
```

Different tests are run in the idaes_examples directory because there is a *pytest.ini* file there. In the root directory, tests are configured by `pyproject.toml`, in the *tool.pytest.ini_options* section.

### Build documentation

The documentation is built using [Jupyterbook][jb].
We have written a thin layer around the Jupyterbook executable, which is installed as a command-line program *idaesx*.
To build the documentation, run:

```shell
idaesx build
```

The output will be in *idaes_examples/nb/_build/html*. As a convenience, you can open that HTML file with the command `idaesx view`.

### Preprocessing

The commands to run tests and build documentation both run a preprocessing step that creates separate copies of the Jupyter notebooks that are used for tests, tutorial exercise and solution, and documentation (see Notebook Names).
These generated files should ***not*** be added to the repository.
If you want to run that preprocessing step separately, use `idaesx pre`.
To remove pre-processed files, run `idaesx clean`.

### Copyright headers

You can add (and update) copyright headers to Python files _and_ Jupyter Notebooks using the 
`addheader` command with the included `addheader.yml` configuration file:

```bash
# first see what would be changed (using -n)
addheader -n -c addheader.yml
# if this is OK, add the headers
addheader -c addheader.yml
```

All existing notebooks and Python files will be automatically discovered and modified as needed.

### Notebook names

Notebooks all have a file name that fits the pattern notebook-name`_ext`.ipynb*.
When creating or modifying notebooks, you should always use `ext` = *src*.
Other extensions are automatically generated when running tests, building the documentation, and manually running the preprocessing step.
See the <a href="#table-nbtypes">table of notebook types</a> for details.

### How to create an example

There are two main steps to creating a new notebook example.

1. Add Jupyter Notebook and supporting files
   1. If this is a new category of notebooks, create a directory. The directory name *should* be in lowercase with underscores between words. For example: 'machine_learning'.
   2. Notebook filename *should* be in lowercase with underscores and ***must*** end with '_src.ipynb'. For example: 'my_example_src.ipynb'.
   3. Add -- in the same directory as the notebook -- any data files, images, or Python files needed for it to run.
2. Add Jupyter notebook to the Jupyterbook table of contents in *idaes_examples/nb/_toc.yml*.
   1. The notebook will be a *section*. If you added a new directory, you will create a new *chapter*, otherwise it will go under an existing one. See [Jupyterbook][1] documentation for more details.
   2. Refer to the notebook as '*path/to/notebook-name*_doc' (replace '_src' with '_doc' and drop the '.ipynb' extension). For example: 'machine_learning/my_example_doc'.
   3. If you created a new directory for this notebook, make sure you add an *index.md* file to it. See other *index.md* files for the expected format.

You *should*  test the new notebook and build it locally before pushing the new file, i.e., run `pytest` and `idaesx build`.

#### Jupyter Notebook file extensions

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

#### Jupyter Notebook cell tags

Preprocessing uses the feature of Jupyter notebook [cell tags][celltags] to understand which additional notebooks to create.

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

#### Jupyter notebook metadata

In addition to per-cell tags, the preprocessor also can look at notebook-level metadata.
This is currently used for only one purpose: to tell the preprocessor not to generate a 'test' notebook, and thereby to skip the given notebook in the tests.
In order to make this happen, either manually edit the notebook source or use the Jupyter notebook "Edit -> Edit Notebook Metadata" menu item to add the following section to the notebook-level metadata:
```
"idaes": {
   "skip": ["test"]
}
```

<!-- 
   References 
-->
[jb]: https://jupyterbook.org/
[hidecell]: https://jupyterbook.org/en/stable/interactive/hiding.html
[celltags]: https://jupyterbook.org/en/stable/content/metadata.html