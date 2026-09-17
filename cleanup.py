#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Removes logs, editor backups, and Python caches from this setup folder.
# The --all flag also clears saved conversation memory.
# Generated replies, model files, and installed skills stay in place.
# ----------------------------------------------------------------------------

import argparse
import glob
import os
import shutil
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

## Delete only matching files and directories contained in this setup.
def main():
    parser = argparse.ArgumentParser(description="Remove runtime logs and caches; optionally clear memory.")
    parser.add_argument("--all", action="store_true", help="Also remove saved memory")
    args = parser.parse_args()
    ## Limit cleanup to known runtime files; output artifacts are not on this list.
    patterns = [
        "**/*~",
        "**/*.log",
        "**/__pycache__",
        "codebase.md",
        ".devcontainer/*~"
    ]
    if args.all: patterns.extend(["memory", "output"])

    for pattern in patterns:
        for target in glob.glob(os.path.join(BASE_DIR, pattern), recursive=True):
            ## Resolve links before checking containment so cleanup cannot escape this folder.
            resolved = os.path.realpath(target)
            if os.path.commonpath([BASE_DIR, resolved]) != BASE_DIR:  continue
            print(f">> Removing {os.path.relpath(target, BASE_DIR)}")

            ## Remove links themselves; only real directories use recursive deletion.
            if os.path.islink(target) or os.path.isfile(target): os.remove(target)
            elif os.path.isdir(target): shutil.rmtree(target)
    print(">> Cleanup complete.")

if __name__ == "__main__": main()
