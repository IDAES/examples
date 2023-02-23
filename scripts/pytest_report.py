"""
Simple processing of the pytest JSON report from pytest-reportlog

Write each failed test to a text file.
These can be browsed in whatever way you want.

Usage (from root of repo)::

   python scripts/pytest_report.py
 """
import argparse
from pathlib import Path
import json
import re


def write_failure(d, o):
    nodeid = o["nodeid"]
    # "idaes_examples/notebooks/flowsheets/methanol_synthesis_test.ipynb::"
    m = re.match(r"(.*)\.[a-z]+::", nodeid)
    if m is None:
        print(f"Cannot understand nodeid = {nodeid}")
        return
    filename = m.group(1).replace("/", "-") + ".txt"
    with (d / filename).open(encoding="utf-8", mode="w") as f:
        f.write(o["location"][0])
        f.write("\n\n")
        lr = o["longrepr"]
        if isinstance(lr, dict):
            s = json.dumps(lr, indent=2)
        else:
            s = str(lr)
        f.write(s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--log", default="pytest-report.log")
    p.add_argument("--dir", default="pytest-reports")
    args = p.parse_args()

    log_file = Path(args.log)
    print(f"Input file: {log_file}")

    output_dir = Path(args.dir)
    output_dir.mkdir(exist_ok=True)
    print(f"Output directory: {output_dir}")
    for old_file in output_dir.glob("*.txt"):
        old_file.unlink()

    f = log_file.open(encoding="utf-8", mode="r")
    n_failed, n_tot = 0, 0
    for line in f:
        o = json.loads(line)
        if "outcome" not in line:
            continue
        if o["outcome"] != "passed":
            write_failure(output_dir, o)
            n_failed += 1
        n_tot += 1

    print(f"Wrote files for {n_failed} test failures (out of {n_tot} tests)")


if __name__ == "__main__":
    main()