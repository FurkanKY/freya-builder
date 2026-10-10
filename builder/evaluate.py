"""Use official practice fixtures only when the supplied brief matches them."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .runtime import digest


def assert_public_suite(documents, brief, kit):
    names = ["brief-a.md"] + (["brief-b.md"] if brief == "B" else [])
    expected = [(Path(kit)/"briefs"/name).read_text() for name in names]
    if brief not in ("A", "B") or [d["text"] for d in documents] != expected:
        raise ValueError("Public suite does not match supplied brief contents")


def summarize(report, suite):
    final = report["final"]
    cases = {row["id"]: row["runs"] > 0 and row["passes"] == row["runs"] for row in final}
    return {"suite":suite, "status":"completed", "case_passes":cases, "passed":sum(cases.values()), "total":len(cases), "seconds":report.get("seconds",0), "raw":report}


def run_evaluation(agent_id, brief, kit, run_dir, budget, trace, env, only=None, reps=1, style=None, personas=None):
    work = Path(run_dir)/"evaluation-kit"
    shutil.copytree(kit, work, dirs_exist_ok=True)
    # The runner creates platform personas keyed by text hash; share its map so reruns reuse them.
    personas = Path(personas) if personas else None
    if personas and personas.exists(): shutil.copy(personas, work/".personas.json")
    output = Path(run_dir)/"evaluation.json"
    command = [sys.executable,str(work/"tools/run_cases.py"),agent_id,"--brief",brief,"--reps",str(reps),"--out",str(output)]
    if only: command += ["--only",only]
    if style: command += ["--style",style]
    cases = json.loads((work/"public-test-set.json").read_text())
    ids = [c["id"] for c in cases if c["brief"]==brief and (not only or c["id"] in only.split(','))]
    if not ids: raise ValueError("No matching public cases")
    # Conservative planning estimate, not a guaranteed server upper bound.
    estimate = 420 * ((len(ids)+4)//5) * reps + 120
    budget.require(estimate)
    suite = digest({"cases_sha":digest(cases),"ids":ids,"reps":reps,"style":style})
    child_env = os.environ.copy()
    child_env.update({k:v for k,v in env.items() if v is not None})
    child_env["PYTHONPATH"] = str(work)
    child_env.pop("FREYA_AGENT_MODEL",None); child_env.pop("FREYA_AGENT_PROVIDER",None)
    trace.emit("test_start",agent_id=agent_id,cases=ids,reps=reps,style=style,suite=suite,estimated_seconds=estimate)
    start=time.monotonic()
    with (Path(run_dir)/"evaluation.log").open("w") as log:
        process=subprocess.Popen(command,cwd=work,env=child_env,stdout=log,stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                if budget.available() <= 1:
                    raise TimeoutError("Test client deadline; server simulation may still be running")
                time.sleep(min(2,budget.available()))
        except BaseException:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            trace.emit("test_interrupted",agent_id=agent_id,server_status="unknown",log=str(Path(run_dir)/"evaluation.log"))
            raise
        finally:
            if personas and (work/".personas.json").exists():
                personas.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(work/".personas.json", personas)
    if process.returncode or not output.exists():
        raise RuntimeError("Official test runner failed; inspect evaluation.log")
    result=summarize(json.loads(output.read_text()),suite)
    trace.emit("test_end",agent_id=agent_id,passed=result["passed"],total=result["total"],seconds=round(time.monotonic()-start,1),suite=suite)
    return result
