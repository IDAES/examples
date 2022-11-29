"""
Copy files from examples-pse into new structure
"""
import argparse
from pathlib import Path
import shutil
import yaml


def copy_files(dirmap: dict, src: Path, tgt: Path, ow: bool = False):
    for item in dirmap["map"]:
        for k, v in item.items():
            src_path = src / k
            tgt_path = tgt / v
            print(f"Copy '{src_path}' -> '{tgt_path}'")
            copy_subdir(src_path, tgt_path, ow)


def copy_subdir(src: Path, tgt: Path, ow: bool):
    stack = [(src, tgt)]
    while stack:
        src, tgt = stack.pop()
        if src.is_dir():
            print(f"Create directory '{tgt}'")
            tgt.mkdir(exist_ok=True, parents=True)
            for s in src.iterdir():
                if s.name not in ("__pycache__", ".ipynb_checkpoints"):
                    t = tgt / s.name
                    stack.append((s, t))
        elif src.name.endswith("-") or src.name.endswith(",cover"):
            continue
        else:
            if src.name.endswith(".ipynb"):
                st = str(tgt)
                for strip_ending in "solution_testing", "testing", "example":
                    if st.endswith("_" + strip_ending + ".ipynb"):
                        st = st[:-(len(strip_ending) + 7)] + ".ipynb"
                        break
                tgt = Path((st[:-6] + "_src.ipynb").lower())
            if (not ow) and tgt.exists():
                print(f"** SKIP ** existing file '{tgt}'")
            else:
                if ow:
                    print(f"Overwrite existing file '{tgt}'")
                print(f"Copy file '{src}' -> '{tgt}'")
                shutil.copy(src, tgt)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source_dir")
    p.add_argument("target_dir")
    p.add_argument("--map", default="map.yml")
    p.add_argument("--overwrite", action="store_true", default=False)
    args = p.parse_args()
    #
    with open(args.map, "r", encoding="utf-8") as mapfile:
        dirmap = yaml.safe_load(mapfile)
        print(f"Loaded map from '{mapfile.name}'")
    copy_files(dirmap, Path(args.source_dir), Path(args.target_dir), ow=args.overwrite)


if __name__ == "__main__":
    main()
