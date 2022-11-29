# Scripts for examples
This directory has utility scripts (and supporting files) for the repository.

**Table of Contents**

* Scripts for examples
  * Migration scripts
  * Other scripts

## Migration scripts

Some of these work together to help migrate files from the older examples-pse repository into the new structure.
They could be run from the root of this repository like this:

```
# Copy notebook files
python copy_files.py \
  ~/src/idaes/examples-pse/src \
  ../idaes_examples/nb \
  --map map.yml

# Generate Jupyterbook table of contents
python generate_toc.py \
  ../idaes_examples/nb \
  --map map.yml \
  --output new_toc.yml

# Add tags to notebook cells
python edit_tags.py \
  ../idaes_examples/nb \
  --map map.yml
  
# Add notebook types (test, doc, etc.)
# to skip during preprocessing for the given notebook
python notebook_skip.py \
  ..\idaes_examples\nb\dae\petsc_chem_src.ipynb \
  test
# To iterate, use your shell's for or foreach
# e.g., in bash:
for nb in ../idaes_examples/nb/dae/*_src.ipynb; do
  python notebook_skip.py $nb test
done
# or in Powershell
foreach ($nb in Get-ChildItem ../idaes-examples/nb/dae -Filter "*_src.ipynb") {
  python notebook_skip.py $nb test
}
```

`map.yml` is a mapping of directories in examples-pse to directories in the new structure.

## Other scripts

* `pytest_report.py` post-processes the JSON report from pytest for human consumption



