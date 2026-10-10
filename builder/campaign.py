"""Development measurement outside the 30-minute build: run the official runner on an existing agent.

    python -m builder.campaign <run_id> --suite AB --reps 3 [--style pieces] [--only ...]
"""
import argparse
import json
from pathlib import Path

from dotenv import dotenv_values
from .runtime import Budget, Trace, write_json
from .evaluate import run_evaluation

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_id"); p.add_argument("--suite", required=True, choices=["A", "B", "AB"])
    p.add_argument("--reps", type=int, default=3); p.add_argument("--style"); p.add_argument("--only")
    a = p.parse_args(argv)
    run_dir = ROOT/"runs"/a.run_id
    result = json.loads((run_dir/"result.json").read_text())
    env = {k: v for k, v in dotenv_values(ROOT/".env").items() if v}
    label = f"campaign-{a.suite}-r{a.reps}" + (f"-{a.style}" if a.style else "") + (f"-{a.only}" if a.only else "")
    out = run_dir/label
    trace = Trace(run_dir/"campaign-trace.jsonl", secrets=[env.get("FREYA_API_KEY"), env.get("FREYA_BANK_TEAM_KEY")])
    report = run_evaluation(result["deployment"]["agent_id"], a.suite, ROOT/"vendor/kit-v3", out, Budget(7200, reserve=0), trace, env,
                            a.only, a.reps, a.style, personas=ROOT/"runs/personas.json")
    write_json(out/"report.json", {k: v for k, v in report.items() if k != "raw"})
    print(json.dumps({k: v for k, v in report.items() if k != "raw"}, indent=1))


if __name__ == "__main__":
    main()
