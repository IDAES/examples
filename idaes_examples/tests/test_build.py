from pathlib import Path
import time
import pytest
from idaes_examples import build, util

# --- preprocess tests ---


@pytest.mark.unit
def test__change_suffix(tmp_path):
    suffix = "test"
    for input, output in (
        ("foo", f"foo_{suffix}"),
        ("foo_bar", f"foo_bar_{suffix}"),
        ("foo_src", f"foo_src_{suffix}"),
        (f"foo_{util.Ext.TEST.value}", f"foo_{suffix}"),
        (f"foo_{util.Ext.SOL.value}", f"foo_{suffix}"),
    ):
        filepath = tmp_path / f"{input}.ipynb"
        with open(filepath, "w") as f:
            f.write("hello, world\n")
        result = build._change_suffix(filepath, suffix)
        assert result.stem == output


@pytest.mark.unit
def test__change_and_update(tmp_path):
    tracking = {"exists": set(), "mtime": set()}
    t0 = time.time()

    # create base file
    p = tmp_path / "foo.ipynb"
    with p.open("w") as f:
        f.write("hello, world\n")

    ext = build.Ext.TEST
    build._change_reason(p, ext, t0, tracking)
    assert tracking["exists"] == {ext.value}

    # create file with target extension
    p2 = tmp_path / f"foo_{ext.value}.ipynb"
    with p2.open("w") as f:
        f.write("hello, world\n")
    compare_time = 1e12  # fake mod. time for base file

    build._change_reason(p, ext, compare_time, tracking)
    assert tracking["mtime"] == {ext.value}


@pytest.mark.component
def test__preprocess(tmp_path):
    name = "foo"
    path = tmp_path / f"{name}.ipynb"

    # create a basic notebook
    with open(path, "w", encoding="utf-8") as f:
        f.write("""{"cells": [""")
        for tag in None, util.Tags.TEST, util.Tags.EX, util.Tags.SOL:
            if tag is None:
                meta_tags = ""
            else:
                f.write(",")
                meta_tags = f'"tags": ["{tag.value}"]'
            f.write(
                f"""{{
                "cell_type": "code",
                "execution_count": 1,
                "id": "9ea6722e",
                "metadata": {{{meta_tags}}},
                "outputs": [],
                "source": ["print('tag={tag}'"]
             }}"""
            )
        f.write("""], "metadata": {},"nbformat": 4,"nbformat_minor": 5}""")

    # debugging
    print("Notebook to preprocess:")
    print("----")
    with open(path, encoding="utf-8") as f:
        print(f.read())
    print("----")

    # preprocess it
    build._preprocess(path)

    # debugging
    print("Notebook files after preprocess step:")
    for nbfile in tmp_path.glob("*.ipynb"):
        print(f"    {nbfile}")

    # look for output notebooks
    for ext in util.ExtAll:
        path = tmp_path / f"{name}_{ext.value}.ipynb"
        assert path.exists()


@pytest.mark.unit
def test_change_notebook_ext():
    for name, expected in (
        ("foo", "foo_ext"),
        ("foo_bar", "foo_bar_ext"),
        (f"foo_{util.Ext.DOC.value}", "foo_ext"),
    ):
        p = Path(name + util.JUPYTER_EXT)
        p2 = util.change_notebook_ext(p, "ext")
        assert p2.name == expected + util.JUPYTER_EXT
