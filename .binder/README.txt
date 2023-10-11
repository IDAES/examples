# Run example notebooks in Binder

Binder (https://mybinder.org) provides a short-lived, temporary Linux cloud environment where Jupyter notebooks can be run without having to install any software locally.

## Quickstart

Click on this button to launch an environment pointing to the current `main` branch of this repository: [![Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/IDAES/examples/HEAD)

## VERY IMPORTANT NOTE

A Binder environment is destroyed automatically after a few minutes of inactivity, which means that **any unsaved progress will be lost**. To avoid this, users should download a copy of a notebook file from the Binder environment to their local machine through the browser (in the Jupyter Lab file browser menu, right click on the notebook file > Download). For more information, see https://mybinder.readthedocs.io/en/latest/about/about.html#how-long-will-my-binder-session-last.

## Customization

Binder uses a Git repository hosted on e.g. GitHub to fetch the notebooks and create the runtime environment.
Users can specify a specific fork, branch, and Git ref (e.g. a particular commit hash), as well as the path to a particular directory or notebook file within the repository, that will be used
when first starting the environment.

These options can be specified interactively on [Binder's homepage](https://mybinder.org/), which will create a URL that can then be shared with others to generate a (separate) instance of the environment with the same repository settings.

Alternatively, the URL can be generated manually according to the following schema:

```txt
https://mybinder.org/v2/gh/<github-org-or-user-name>/<github-repo-name>/<git-ref>?labpath=<path-to-notebook>
```

Example, for branch `mybranch` of `myuser`'s fork of this repository, pointing to the `idaes_examples/notebooks/docs/tut/introduction_exercise.ipynb` notebook file:

```txt
https://mybinder.org/v2/gh/myuser/examples/mybranch?labpath=idaes_examples/notebooks/docs/tut/introduction_exercise.ipynb
```
