---
Author: Dan Gunter
Revised: 7 December 2022
---

**Table of Contents**

* IDAES Examples Tutorial
  * Setup
    * Fork and clone the repository
    * Install in a Conda environment
* How to create a new example
  * Create a notebook
    * Start Jupyter
    * Add a markdown cell
    * Add code cells
    * Add tags
    * Save work
  * Add the example to the table of contents
  * Test the example
* How to copy an example from the examples
  * Determine where the notebook goes in the
  * Determine the new notebook filename
  * Copy the notebook
  * Fix tags
  * Update copyright headers
  * Test and build changes
* Other tasks
  * Run
  * Rebuild the documentation
  * Format the notebooks with Black
    * Browse the notebooks

# IDAES Examples Tutorial

This is for developers. Users should refer to the "readme.md" file in this directory.

Assumptions:
* user = 'username'

## Setup

### Fork and clone the repository


Go to https://github.com/IDAES/examples and fork the repository.

Start a shell and change to directory where you will clone the repository.
```
git clone  https://github.com/username/examples
cd examples
git remote add upstream  https://github.com/username/examples
```

### Install in a Conda environment

Continue in the directory where you cloned the repository.
Create a conda environment and install examples (and dependencies, including idaes-pse).

```
conda create -y -n idaes-examples python=3
conda activate idaes-examples
pip install -e .[dev]
idaes get-extensions
```

Note #1: The "pip install" step will provide time to brew some coffee, get a snack, or see why the kids are so quiet (depending on your particular circumstances).

Note #2: The `idaes get-extensions` command makes *global* changes, so use the `--to` option or skip this step if you need to keep a specific version of the extensions installed for other work.

# How to create a new example

We will walk through the steps for a new example Jupyter Notebook

## Create a notebook

Continue in the directory where you cloned the repository.
Create a Jupyter notebook in an existing folder.

### Start Jupyter

Change to a subdirectory and start the Jupyter notebook server:
```
cd idaes_examples/nb/flowsheets
jupyter notebook &
```

### Add a markdown cell

Then, in the Jupyter notebook browser, create a new blank note book ("New" -> "IPython 3 kernel").
Name the notebook `my_notebook_src` and make the first cell a Markdown cell with the following text:
```
# My notebook
This is my example notebook.
```

### Add code cells

Add 3 code cells with the following content (one statement per cell):
```
import idaes

print(idaes.__version__)

assert idaes.__version__.startswith('2')
```

### Add tags

To demonstrate how the tags work, we will add tags to a couple of these cells:
1. To see current tags, select "View" -> "Cell toolbar" -> "Tags".
2. Add the tag `noauto` to the cell with the print statement
3. Add the tag `testing` to the cell with the assert statement

### Save work

Finally, save the notebook.

## Add the example to the table of contents

For building and testing to 'see' a notebook it needs to be in the Jupyterbook table of contents.
The following steps add the new notebook to the table of contents.

1. Open `idaes_examples/nb/_toc.yml` in an editor.
2. Find `- file: flowsheets/index` under `chapters:`.
3. In the list of sections for that chapter, add `- file: flowsheets/my_notebook_doc` (indent the same as the other sections).
4. Save the modified file.

Note: Although the notebook was called `my_notebook_src`, the filename in the table of contents entry is `my_notebook_doc`.


## Test the example

Example notebooks are tested with `pytest`, using a special configuration that is stored in the root directory of the repository (in the file "pyproject.toml").

Change to the top directory for the repository, then test your new example notebook with: 
```
pytest -k my_notebook
```

Why `-k`? Although you can test *all* notebooks with the simple command `pytest`, since notebooks are found and tested with an extra level of indirection you can't simply name the notebook directly. Instead, testing a single notebook requires using a "-k" expression that will match the notebook.


# How to copy an example from the examples-pse repo

In the transition period, there may be changes to example notebooks, etc. in `examples-pse` that need to be moved over into this repo.
There are bulk migration scripts in the 'scripts/' directory, but the intent of this mini-tutorial is to help migrate one example notebook (though there is one file in that directory we will use).

## Determine where the notebook goes in the "new" layout

In `scripts/map.yml` there is a mapping of the notebook subdirectories in examples-pse, undder `src/` 
to the subdirectories under `idaes_examples/nb/` in this repository.
For example:
```yaml
map:
    - Examples/DAE: dae
    - # ..etc..
```
This means that the notebook `src/Examples/DAE/petsc_chem_example.ipynb` in the examples-pse repo
should be placed in `idaes_examples/dae/petsc_chem_src.ipynb` in the new repo.

## Determine the new notebook filename

Filenames will mostly stay the same, **but** certain suffixes on the old files should 
be stripped, and the new suffix `_src` added.

So, all of the following..
* `foo_example.ipynb`
* `foo_solution_testing.ipynb`
* `foo_testing.ipynb`
* `foo.ipynb`

..should be copied to the file `foo_src.ipynb` in the new structure.

## Copy the notebook

You should probably back up the old version first. Then copy the file, e.g. in
the previous example if `examples-pse` and `examples` were cloned in the same parent directory,
you could do, from the `examples` top-level directory:
```shell
# backup
cp idaes_examples\nb\dae\petsc_chem_src.ipynb idaes_examples\nb\dae\petsc_chem_src.bak
# overwrite
cp ..\examples-pse\src\Examples\DAE\petsc_chem_example.ipynb .\idaes_examples\nb\dae\petsc_chem_src.ipynb
```

## Fix tags

To see current cell tags in the notebook, open it with the Jupyter Notebook UI and then
select "View" -> "Cell toolbar" -> "Tags".
You should go through the notebook and take out any `remove_cell` tags.

You can also, if you want, use additional tags available in the new framework.
See the 'Jupyter Notebook cell tags' section of the readme.md in this directory.

## Update copyright headers

To add or update copyright headers, you can run `addheader` in the root directory.
This will look at all files but should only change notebooks where needed.

## Test and build changes

Refer to the 'Test the example' section above for how to test-run the
notebook with pytest, and also the 'Other tasks' section for how to build documents
and run Black formatting.

# Other tasks

## Run 'unit' tests for all examples

To do quick sanity checks and other tests of the example notebooks, there are standard Python test files under `idaes_examples/nb`. To run those *instead* of the example notebooks, simply run pytest from the `idaes_examples` sub-directory:
```
cd idaes_examples
pytest
```

Note: This works because there is a "pytest.ini" in that directory that is used instead of the configuration in the root of the repository. That configuration does not set up the special ('nbmake') configuration for running Jupyter notebooks under pytest.

## Rebuild the documentation

To build (or rebuild) the documentation:
```
idaesx build
```

Note #1: This rebuilds *all* the docs, which also involves executing them. This could take many minutes.
Note #2: From the output you can see that "Jupyterbook" is really doing most of the work here.
Note #3: In theory rebuilding the docs after the first time can re-use all the previously built versions and save a lot of time. Getting Jupyterbook caching working has been harder than anticipated.

When the documentation finally finished building, the HTML output will be in `idaes_examples\nb\_build\html`. To view, open the "index.html" file with a browser.

## Format the notebooks with Black

To make sure the notebook code is formatted according to IDAES convention, you can run [Black](https://black.readthedocs.io/en/stable/) on all the notebooks:

```
idaesx black
```

### Browse the notebooks

There is a simple embedded GUI for browsing the notebooks.
While, of course, you can navigate to the notebooks with Jupyter's file browser, the GUI has the
advantage of giving notebook descriptions as you browse.

```
idaesx gui
```

Note #1: Due to the limitations of the Tk toolkit, the font is pretty ugly. Sorry.
Note #2: The first markdown cell with a header is used for the description.
