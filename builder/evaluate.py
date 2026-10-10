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
    # Suite AB runs every public case against the A+B agent: Brief B keeps all Brief A rules.
    names = ["brief-a.md"] + (["brief-b.md"] if brief in ("B", "AB") else [])
    expected = [(Path(kit)/"briefs"/name).read_text() for name in names]
    if brief not in ("A", "B", "AB") or [d["text"] for d in documents] != expected:
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
    command = [sys.executable,str(work/"tools/run_cases.py"),agent_id,"--reps",str(reps),"--out",str(output)]
    if brief != "AB": command += ["--brief",brief]
    if only: command += ["--only",only]
    if style: command += ["--style",style]
    cases = json.loads((work/"public-test-set.json").read_text())
    ids = [c["id"] for c in cases if (brief=="AB" or c["brief"]==brief) and (not only or c["id"] in only.split(','))]
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


def transcript_digest(messages, limit=6000):
    """Conversation turns and bank tool calls only; drops engine events and embedded code."""
    lines = []
    for m in messages or []:
        role, text = m.get("role"), m.get("message") or m.get("content") or ""
        if role in ("assistant", "user", "bot"):
            lines.append(f"{role.upper()}: {text}")
            continue
        try:
            event = json.loads(text) if isinstance(text, str) and text.startswith("{") else {}
        except ValueError:
            event = {}
        name = event.get("function")
        if not name or name in ("code_exec", "end_call"):
            continue
        if event.get("event") == "function_call_start":
            body = (event.get("args") or {}).get("body")
            lines.append(f"TOOL CALL {name if name != 'api_call' else 'get_account'}: {json.dumps(body)}")
        elif event.get("event") == "function_call_complete":
            data = (event.get("result") or {}).get("data")
            if isinstance(data, dict):
                data = {k: v for k, v in data.items() if k != "what_to_do_next"}
            lines.append(f"TOOL RESULT {name if name != 'api_call' else 'get_account'}: {json.dumps(data)[:400]}")
        elif event.get("event") == "function_call_error":
            lines.append(f"TOOL ERROR {name}: {str(event.get('error'))[:300]}")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"
