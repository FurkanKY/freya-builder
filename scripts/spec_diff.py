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


def _labels(runs):
    """Short names for the output: a run id as given, a spec file by the fewest parent folders that tell the files apart."""
    paths = [Path(r) for r in runs]
    for depth in (1, 2, 3):
        labels = ["/".join(p.parts[-1 - depth:-1]) if p.is_file() else str(p) for p in paths]
        if len(set(labels)) == len(labels):
            return labels
    return runs


def main(args):
    runs = [a for a in args if not a.startswith("--")]
    specs = []
    for run in runs:
        # A run id, or a spec file written by another tool.
        path = Path(run) if Path(run).is_file() else ROOT/"runs"/run/"candidate-a.json"
        data = json.loads(path.read_text())
        specs.append(flat(data.get("spec", data) if isinstance(data, dict) else {}))
    labels = _labels(runs)
    keys = sorted(k for k in set().union(*specs) if "--all" in args or not k.startswith(TEXT))
    same = 0
    for key in keys:
        values = [json.dumps(s.get(key), ensure_ascii=False, sort_keys=True) for s in specs]
        if len(set(values)) == 1:
            same += 1
            continue
        print(f"== {key}")
        for label, v in zip(labels, values):
            print(f"   {label}: {v[:400]}")
    print(f"{same} of {len(keys)} fields agree across {len(runs)} runs")


if __name__ == "__main__":
    main(sys.argv[1:])
