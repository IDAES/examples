"""
Edit tags in files (use after copy-files.py)
"""
import argparse
from pathlib import Path
import json
import yaml


def edit_tags(m: dict, d: Path):
    for item in m["map"]:
        for _, dirname in item.items():
            p = d / dirname
            for nb in p.glob("*_src.ipynb"):
                print(f"Edit tags in notebook '{nb}'")
                with nb.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if _edit(data):
                    with open(nb, "w", encoding="utf-8") as f:
                        print("Write new notebook")
                        json.dump(data, f)


def _edit(d) -> bool:
    any_edited = False
    for cell in d["cells"]:
        meta = cell["metadata"]
        new_tags, edited = [], False
        for tag in meta.get("tags", ()):
            if tag == "remove_cell":
                print("- removed tag: 'remove_cell'")
                edited = True
            else:
                new_tags.append(tag)
        if edited:
            meta["tags"] = new_tags
            any_edited = True
    return any_edited


def main():
    p = argparse.ArgumentParser()
    p.add_argument("target_dir")
    p.add_argument("--map", default="map.yml")
    args = p.parse_args()
    #
    with open(args.map, "r", encoding="utf-8") as mapfile:
        dirmap = yaml.safe_load(mapfile)
        print(f"Loaded map from '{mapfile.name}'")
    edit_tags(dirmap, Path(args.target_dir))


if __name__ == "__main__":
    main()
