"""Copy one finished run into submission/: python -m builder.submit <run_id> <brief-name>.

Checks that the run ended with a validated or evaluated export whose hash matches result.json,
then writes <brief-name>.workflow.json and the run's trace next to it. Nothing is changed on Freya.
"""
import argparse
import json
import shutil
from pathlib import Path

from .runtime import digest

ROOT = Path(__file__).resolve().parent.parent


def submit(run_id, name, root=ROOT):
    run = Path(root)/"runs"/run_id
    result = json.loads((run/"result.json").read_text())
    if result.get("status") not in ("validated", "evaluated"):
        raise ValueError(f"Run {run_id} did not finish with an export (status {result.get('status')})")
    export = json.loads((run/"final.workflow.json").read_text())
    if digest(export) != result.get("export_sha256"):
        raise ValueError("final.workflow.json does not match the hash recorded in result.json")
    if set(export) != {"workflow_id", "agent_id", "updated_at", "workflow"}:
        raise ValueError("Export is not in the freya.export_workflow format")
    out = Path(root)/"submission"
    out.mkdir(exist_ok=True)
    shutil.copy(run/"final.workflow.json", out/f"{name}.workflow.json")
    shutil.copy(run/"trace.jsonl", out/f"{name}.trace.jsonl")
    if (run/"trace.txt").exists():
        shutil.copy(run/"trace.txt", out/f"{name}.trace.txt")
    return {"run_id": run_id, "workflow_id": export["workflow_id"], "agent_id": export["agent_id"],
            "export_sha256": result["export_sha256"], "files": sorted(p.name for p in out.glob(f"{name}.*"))}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_id")
    p.add_argument("name", help="brief name used for the submitted files, e.g. final-1")
    a = p.parse_args(argv)
    print(json.dumps(submit(a.run_id, a.name), indent=2))


if __name__ == "__main__":
    main()
