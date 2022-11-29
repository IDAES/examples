"""
Control notebook level tags to skip (when preprocessing notebooks).
"""
import argparse
from enum import Enum
import json
import sys
from typing import List
from idaes_examples.util import NB_META

# dict keys
IDAES, SKIP = "idaes", "skip"

class Actions(Enum):
    add = "add"
    remove = "remove"
    show = "show"


def get_idaes_meta(nb):
    if NB_META in nb and IDAES in nb[NB_META]:
        return nb[NB_META][IDAES]
    return None


def modify_tags(nb, tags=None, action: Actions = None) -> bool:
    changed = False
    meta = get_idaes_meta(nb)
    if meta:
        cur_skip, tags = set(meta[SKIP]), set(tags)
        if action == Actions.remove:
            new_skip = cur_skip - tags
        else:
            new_skip = cur_skip.union(tags)
        if new_skip != cur_skip:
            meta[SKIP], changed = list(new_skip), True
    elif action == Actions.add:
        nb[NB_META][IDAES], changed = {SKIP: tags}, True
    return changed


def get_action(action) -> List[Actions]:
    action = action.lower()
    matches = []
    for a in Actions:
        if len(action) > len(a.value):
            continue
        matched = True
        for i, ltr in enumerate(action):
            if a.value[i] != action[i]:
                matched = False
                break
        if matched:
            matches.append(a)
    return matches


def show_tags(nb):
    meta = get_idaes_meta(nb)
    if meta:
        skip_tags = ", ".join(meta.get(SKIP, []))
        if skip_tags:
            print(f"Tags for '{SKIP}': {skip_tags}")
        else:
            print(f"No tags for '{SKIP}'")
    else:
        print("No metadata section")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("notebook", help="Notebook to modify (by default, add tags)")
    p.add_argument("tags", nargs="*", help="List of tags")
    p.add_argument(
        "--action",
        "-a",
        help=f"Action to take: add, remove, show (default is '{Actions.add.value}')",
        default=Actions.add.value,
        metavar="NAME",
    )

    args = p.parse_args()
    matches = get_action(args.action)
    if len(matches) == 0:
        p.error(f"Action '{args.action}' not recognized")
    elif len(matches) > 1:
        p.error(f"Action '{args.action}' is ambiguous")
    action = matches[0]

    # load notebook
    print(f"| Load notebook '{args.notebook}'")
    with open(args.notebook, mode="r", encoding="utf-8") as nb_file:
        nb_data = json.load(nb_file)

    # run
    print(f"| Perform action: {action.value}")
    if action == Actions.show:
        show_tags(nb_data)
    else:
        ok = modify_tags(nb_data, tags=args.tags, action=action)
        if ok:
            # if modified, write back new data
            print("| Writing back changed notebook")
            with open(args.notebook, mode="w", encoding="utf-8") as nb_file:
                json.dump(nb_data, nb_file)
        else:
            print("Notebook tags not changed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
