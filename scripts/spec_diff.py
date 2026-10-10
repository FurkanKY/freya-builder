"""Compare the bank specs that two or more builder runs extracted from the same brief.

    .venv/bin/python scripts/spec_diff.py <run_id> <run_id> [...] [--all]

The model call that reads the brief is the one random step of a build. Runs whose specs agree are a sign
the brief was read the same way; a field where they differ is the place to check against the brief before
choosing which run to submit. Free-text fields (policy, tool descriptions and hints) are compared only with --all.
Nothing is changed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def flat(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(flat(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        out = {}
        for i, v in enumerate(value):
            out.update(flat(v, f"{prefix}[{i}]"))
        return out
    return {prefix: value}


TEXT = ("policy", "tool_descriptions", "tool_field_hints")


def main(args):
    runs = [a for a in args if not a.startswith("--")]
    specs = []
    for run in runs:
        data = json.loads((ROOT/"runs"/run/"candidate-a.json").read_text())
        specs.append(flat(data.get("spec") or {}))
    keys = sorted(k for k in set().union(*specs) if "--all" in args or not k.startswith(TEXT))
    same = 0
    for key in keys:
        values = [json.dumps(s.get(key), ensure_ascii=False, sort_keys=True) for s in specs]
        if len(set(values)) == 1:
            same += 1
            continue
        print(f"== {key}")
        for run, v in zip(runs, values):
            print(f"   {run}: {v[:400]}")
    print(f"{same} of {len(keys)} fields agree across {len(runs)} runs")


if __name__ == "__main__":
    main(sys.argv[1:])
