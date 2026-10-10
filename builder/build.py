"""Single entry point: python -m builder.build BRIEF TOOL_API [--suite A]."""
import argparse
import asyncio
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    __package__="builder"

from dotenv import dotenv_values
from .runtime import Budget, Trace, digest, load_inputs, validate_workflow, write_json, select_candidate, walk
from .generate import generate
from .freya_client import Client
from .evaluate import assert_public_suite, run_evaluation, transcript_digest

ROOT=Path(__file__).resolve().parent.parent
KIT=ROOT/"vendor/kit-v3"


def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs",nargs="*")
    p.add_argument("--brief",action="append")
    p.add_argument("--tool-api")
    p.add_argument("--slot")
    p.add_argument("--suite",choices=["A","B","AB"])
    p.add_argument("--only")
    p.add_argument("--reps",type=int,default=1)
    p.add_argument("--style",choices=["pieces","corrects","talkative","asks_back","in_words"])
    p.add_argument("--repair",action="store_true")
    p.add_argument("--seconds",type=int,default=1800)
    p.add_argument("--model")
    a=p.parse_args(argv)
    if a.inputs:
        if a.brief or a.tool_api or len(a.inputs)<2: p.error("Use either positional BRIEF... API or --brief/--tool-api")
        a.brief,a.tool_api=a.inputs[:-1],a.inputs[-1]
    if not a.brief or not a.tool_api: p.error("Brief and tool API are required")
    if not 180<=a.seconds<=1800: p.error("--seconds must be between 180 and 1800")
    if not 1<=a.reps<=3: p.error("--reps must be between 1 and 3")
    if (a.only or a.style or a.repair) and not a.suite: p.error("Test options require explicit --suite")
    return a


async def execute(a):
    budget=Budget(a.seconds)
    env={k:v for k,v in dotenv_values(ROOT/".env").items() if v is not None}
    for key in ("FREYA_API_KEY","FREYA_BANK_TEAM_KEY","FREYA_WORKSPACE_ID","FREYA_API_URL","BUILDER_MODEL"):
        if os.environ.get(key): env[key]=os.environ[key]
    if not env.get("FREYA_API_KEY"): raise ValueError("Set FREYA_API_KEY in project .env")
    if a.suite and len(env.get("FREYA_BANK_TEAM_KEY", ""))<16: raise ValueError("Practice team key must contain at least 16 characters")
    inputs=load_inputs(a.brief,a.tool_api)
    if a.suite:
        assert_public_suite(inputs["briefs"],a.suite,KIT)
        if inputs["api"] != json.loads((KIT/"tools/openapi.json").read_text()):
            raise ValueError("Public suite requires the matching public OpenAPI")
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    run_dir=ROOT/"runs"/run_id; run_dir.mkdir(parents=True)
    trace=Trace(run_dir/"trace.jsonl",secrets=[env.get("FREYA_API_KEY"),env.get("FREYA_BANK_TEAM_KEY")])
    model=a.model or env.get("BUILDER_MODEL") or "sonnet"
    commit=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    dirty=bool(subprocess.run(["git","status","--porcelain"],cwd=ROOT,capture_output=True,text=True).stdout)
    trace.emit("build_start",run_id=run_id,input_fingerprint=inputs["fingerprint"],kit_version=3,commit=commit,dirty=dirty,model=model,seconds=a.seconds)
    write_json(ROOT/"runs/latest.json",{"run_id":run_id,"path":str(run_dir),"status":"running"})
    write_json(run_dir/"inputs.json",inputs)
    client=Client(env["FREYA_API_KEY"],budget,workspace_id=env.get("FREYA_WORKSPACE_ID"),state_path=ROOT/"runs/platform-state.json",url=env.get("FREYA_API_URL","https://staging-app.freyavoice.ai"))
    slot=a.slot or inputs["fingerprint"][:12]
    selected=None
    report={"status":"not_evaluated"}
    try:
        candidate=await generate(inputs,KIT,budget,trace,model,run_dir)
        for attempt in range(2):
            errors=validate_workflow(candidate["workflow"],inputs["api"])
            if not errors: break
            trace.emit("validation_failed",errors=errors)
            if attempt==1: raise ValueError("Workflow still invalid after one structural repair")
            candidate=await generate(inputs,KIT,budget,trace,model,run_dir,previous=candidate,feedback={"structural_errors":errors})
        client.validate(candidate["workflow"])
        write_json(run_dir/"candidate-a.json",candidate)
        deployment=client.publish(slot+"-a",candidate["workflow"])
        checkpoint=client.export(deployment["workflow_id"])
        write_json(run_dir/"candidate-a.workflow.json",checkpoint)
        selected={"label":"a","candidate":candidate,"deployment":deployment,"export":checkpoint}
        trace.emit("workflow_published",**deployment,candidate_sha256=digest(candidate["workflow"]),nodes=len(candidate["workflow"]["nodes"]),tools=sum("function" in node for _,node in walk(candidate["workflow"])))
        if a.suite:
            report=run_evaluation(deployment["agent_id"],a.suite,KIT,run_dir/"test-a",budget,trace,env,a.only,a.reps,a.style,personas=ROOT/"runs/personas.json")
            write_json(run_dir/"report-a.json",report)
            raw=report["raw"]
            runs=client.simulation_runs(raw["simulation_id"],raw["iteration_id"])
            versions=sorted({str(row["agentVersionNumber"]) for row in runs.get("runs",[]) if row.get("agentVersionNumber") is not None})
            trace.emit("tested_versions",expected=deployment["version"],observed=versions)
            if versions and versions != [str(deployment["version"])]:
                raise RuntimeError("Simulation did not use the selected published version")
            if a.repair and report["passed"]<report["total"] and budget.available()>1020:
                evidence=[]
                for row in raw.get("rows",[]):
                    if not row["pass"]:
                        call=client.call(row["call_id"]) if row.get("call_id") else {}
                        evidence.append({"case":row["id"],"failed":row["failed"],"transcript":transcript_digest(call.get("messages",[]))})
                repaired=await generate(inputs,KIT,budget,trace,model,run_dir,previous=candidate,feedback=evidence)
                errors=validate_workflow(repaired["workflow"],inputs["api"])
                if errors: trace.emit("challenger_rejected",errors=errors)
                else:
                    client.validate(repaired["workflow"])
                    new_dep=client.publish(slot+"-b",repaired["workflow"])
                    new_export=client.export(new_dep["workflow_id"])
                    write_json(run_dir/"candidate-b.json",repaired)
                    write_json(run_dir/"candidate-b.workflow.json",new_export)
                    new_report=run_evaluation(new_dep["agent_id"],a.suite,KIT,run_dir/"test-b",budget,trace,env,a.only,a.reps,a.style,personas=ROOT/"runs/personas.json")
                    write_json(run_dir/"report-b.json",new_report)
                    choice=select_candidate(report,new_report)
                    trace.emit("candidate_selection",choice=choice)
                    if choice=="challenger":
                        selected={"label":"b","candidate":repaired,"deployment":new_dep,"export":new_export}
                        report=new_report
            elif a.repair:
                trace.emit("repair_skipped",reason="all cases passed or insufficient repair-and-retest budget",available_seconds=round(budget.available()))
        result={"status":"evaluated" if report["status"]=="completed" else "validated","selected":selected["label"],"deployment":selected["deployment"],"report":{k:v for k,v in report.items() if k!="raw"}}
        write_json(run_dir/"final.workflow.json",selected["export"])
        result["export"]=str(run_dir/"final.workflow.json")
        result["export_sha256"]=digest(selected["export"])
        trace.emit("build_end",**result,remaining_seconds=round(budget.remaining()))
        write_json(run_dir/"result.json",result)
        write_json(ROOT/"runs/latest.json",{"run_id":run_id,"path":str(run_dir),**result})
        return 0
    except Exception as exc:
        trace.emit("build_failed",error_type=type(exc).__name__,detail=str(exc),checkpoint_exists=selected is not None)
        result={"status":"failed","error_type":type(exc).__name__,"trace":str(trace.path),"checkpoint":str(run_dir/"candidate-a.workflow.json") if selected else None}
        write_json(run_dir/"result.json",result)
        write_json(ROOT/"runs/latest.json",{"run_id":run_id,"path":str(run_dir),**result})
        return 1


def main(argv=None):
    args=parse_args(argv)
    (ROOT/"runs").mkdir(exist_ok=True)
    with (ROOT/"runs/build.lock").open("w") as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another builder process is running; no second run started",file=sys.stderr); return 2
        return asyncio.run(execute(args))


if __name__=="__main__":
    raise SystemExit(main())
