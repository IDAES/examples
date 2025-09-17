# Introduction

This documentation contains examples for the IDAES platform.

## About IDAES

The Institute for Design of Advanced Energy Systems (IDAES) 
{cite}`miller2018idaes` was originated to bring the 
most advanced modeling and 
optimization capabilities to the challenges of transforming and decarbonizing the world’s energy systems to make them 
environmentally sustainable while maintaining high reliability and low cost.
For more information please see the [IDAES website](https://idaes.org/) and the online 
[IDAES documentation](https://idaes-pse.readthedocs.io/en/latest/index.html).

## About this documentation

The examples in this documentation show how to create, configure, and solve IDAES models for a variety of application.
Some of the examples are written in a tutorial style with separate "exercise" and "solution" sections to
facilitate use in a group setting.

All of the examples are written in Python as [Jupyter](https://jupyter.org) notebooks.
You can browse these notebooks online or download them to and run on your own machine.
The online examples have been created with the 
[JupyterBook](https://jupyterbook.org) software package.

### Prerequisites

**Install the latest version of IDAES.** Examples in this documentation are rigorously *tested* to ensure that they work with the *latest* version of the IDAES 
software. 
For more information on installing IDAES on your platform,
please refer to the [IDAES documentation](https://idaes-pse.readthedocs.io/en/latest/index.html).

**Learn about mathematical optimization and Pyomo.** IDAES is a state-of-the-art equation-oriented modeling and optimization environment. Below are recommended topics and references:
* *Mathematical optimization* especially nonlinear programs (optimization problems) and chemical engineering applications. {cite}`Postek2025`, along with the [companion website](https://mobook.github.io/MO-book/intro.html) and [overview video](https://www.youtube.com/watch?v=DPv-7TeSTNs), are the best resources for a user new to mathematical optimization. {cite}`biegler1997systematic`, {cite}`biegler2010nonlinear`, and {cite}`grossmann2021advanced` are excellent references for advanced users. The [Prof. Dowling's course website](https://ndcbe.github.io/optimization/intro.html) includes Jupyter notebooks and Pyomo examples inspired by these texts.
* *Pyomo*. IDAES is built upon Pyomo, which is an open-source algebraic modeling environment. New users will likely find {cite}`Postek2025` along its [companion website](https://mobook.github.io/MO-book/intro.html) and the [ND Pyomo Cookbook](https://ndcbe.github.io/ND-Pyomo-Cookbook/README.html) as the easiest introduction to Pyomo. Other excellent resources include {cite}`bynum2021pyomo` and the [Pyomo documentation](https://pyomo.readthedocs.io/en/stable/).

### Getting the source code
The full source code for these examples is available from the 
[IDAES examples repository](https://github.com/IDAES/examples) on GitHub.
It may also be installed as a Python package from [PyPI](https://pypi.org/) with the command:

```
pip install idaes-examples
```

Please see the `README.md` file
in the [repository](https://github.com/IDAES/examples) for more information.

## Getting help

If you find the content of the examples hard to understand, or perhaps incorrect,
please reach out to us. Our primary public forum is the 
[idaes-pse discussions page](https://github.com/IDAES/idaes-pse/discussions),
where you can post questions and also see if others have had a similar
problem. You may also contact us directly by sending email to 
[idaes-support@idaes.org](mailto:idaes-support@idaes.org).


## Bibliography

```{bibliography}
```