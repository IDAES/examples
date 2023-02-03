# Examples README

This file provides details about the internal organization of the example notebooks and supporting files.

## Directories
The examples are divided into a few top-level directories.
These directories are used to separate different purposes for the contained files:

* `docs`: Examples and tutorials that will be tested and also published in the online documentation.
* `internal`: Examples and tutorials that will not be published in the online documentation.  
  This directory has two 
  subdirectories:
    * `active`: Not published but tested against new PRs
    * `archive`: Not published and *not* tested against new PRs
* `_dev`: Notebooks for developers only.
Currently, a set of noteboooks demonstrating cell tags (see top-level 
  `README.md` for details).

## Where to put a new notebook

Use the following to decide where to put any new Jupyter notebook:

1. Will it be included in the online docs?  
**Yes**: Put under `docs`  
**No**: Go to 2
2. Will it be actively maintained to handle any changes in IDAES core?  
**Yes**: Put under `internal/active`  
**No**: Put under `internal/archive`

All these directories have their own subdirectories for grouping similar notebooks. Place the new notebook in an appropriate subdirectory.

