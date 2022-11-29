"""
Generate the _toc.yml for Jupyterbook from the notebooks in the map
"""

import argparse
from pathlib import Path
import json
import re
import sys
import yaml


class TableOfContents:
    def __init__(self, m: dict, d: Path):
        self._body = {
            "format": "jb-book",
            "root": "index",
            "parts": [
                {"caption": "Flowsheets",
                 "chapters": []}
            ],
        }
        self._titles = {}
        for item in m["map"]:
            for _, dirname in item.items():
                p = d / dirname
                self._add_index(p)
                self._add_chapter(dirname)
                print(f"Look for notebooks in '{p}'")
                for nb in p.glob("*_src.ipynb"):
                    filename = nb.stem[:-4]
                    self._add_section(dirname, filename)

    def dump(self, strm):
        yaml.dump(self._body, strm)

    def _add_chapter(self, d):
        chapters = self._body["parts"][0]["chapters"]
        chapters.append({
            "file": f"{d}/index",
            "sections": []
        })

    def _add_section(self, d, s):
        chapters = self._body["parts"][0]["chapters"]
        for c in chapters:
            if c["file"][:c["file"].rfind("/")] == d:
                entry = {"file": f"{d}/{s}_doc"}
                c["sections"].append(entry)


    def _add_index(self, p):
        idx = p / "index.md"
        print(f"Add index at '{idx}'")
        if idx.exists():
            print("**SKIP** index exists")
        else:
            with open(idx, "w", encoding="utf-8") as f:
                f.write(f"# Title\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("target_dir")
    p.add_argument("--map", default="map.yml")
    p.add_argument("--output", default=None)
    args = p.parse_args()
    #
    with open(args.map, "r", encoding="utf-8") as mapfile:
        dirmap = yaml.safe_load(mapfile)
        print(f"Loaded map from '{mapfile.name}'")
    toc = TableOfContents(dirmap, Path(args.target_dir))
    if args.output is None:
        toc.dump(sys.stdout)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            toc.dump(f)


if __name__ == "__main__":
    main()
