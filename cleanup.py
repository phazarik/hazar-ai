#!/usr/bin/env python3
import os
import glob
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--all", action="store_true", help="Remove analysis output files (*.root, *.txt)")
args = parser.parse_args()
script_dir = os.path.dirname(os.path.abspath(__file__))

## Default cleanup: Editor backups and ROOT ACLiC compilation artifacts
junk = [
    "**/*~",
    "**/*.log",
    "**/__pycache__",
    "codebase.md"
]
## --all cleanup: Output ROOT files and text summaries
if args.all:
    junk += [
        "memory/"
    ]

for f in junk:
    matches = glob.glob(os.path.join(script_dir, f), recursive=True)
    for match in matches:
        cmd = f'rm -rf "{match}"'
        print(f">> {cmd}")
        os.system(cmd)

print("Done!")