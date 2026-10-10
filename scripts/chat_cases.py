"""Run kit cases against the published workflow over /api/v2/chat/message, with no simulation slot.

The customer is played by Claude (claude CLI) from the kit's own persona text; the bank ledger is scored by the kit's
score_ledger, and the case's conversation checks by a Claude judge over the transcript plus the tool calls.
A proxy for the platform simulation (gemini persona and judge), not the same thing.

Usage (from the repo root):
  chat_cases.py <workflow_id> [--brief A|B] [--only PUB-01,PUB-12] [--cases file.json] [--reps 3] [--style talkative]
                [--workers 5] [--out results.json] [--infra-retries 2]
Never prints secrets."""
import argparse, json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import dotenv_values

for k, v in dotenv_values(".env").items():
    if v is not None:
        os.environ.setdefault(k, v)
sys.path.insert(0, "vendor/kit-v3"); sys.path.insert(0, "vendor/kit-v3/tools")
import freya
from score import http, score_ledger
from run_cases import persona_for

LOCK = threading.Lock()
PERSONA_MODEL = os.environ.get("CHAT_PERSONA_MODEL", "sonnet")


def claude(system, text, model, timeout=120):
    for attempt in range(3):
        try:
            out = subprocess.run(["claude", "-p", "--model", model, "--system-prompt", system, "--tools", "",
                                  "--no-session-persistence", "--setting-sources", ""],
                                 input=text, capture_output=True, text=True, timeout=timeout)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        time.sleep(3)
    return ""


def say(wid, variables, call_id, text):
    body = {"workflowId": wid, "message": text, "customerVariables": variables}
    if call_id:
        body["callId"] = call_id
    r = freya.api("POST", "/api/v2/chat/message", body)
    r = r.get("result") or r
    return str(r.get("response") or ""), r.get("callId") or call_id


def trace(call_id):
    """Turns and tool calls up to the first call_ended event, from the call record."""
    d = freya.get_call(call_id)
    lines, ended = [], False
    for m in d.get("messages", []):
        if m.get("role") in ("user", "assistant", "bot"):
            lines.append(("CUSTOMER: " if m["role"] == "user" else "AGENT: ") + str(m.get("message") or ""))
            continue
        try:
            e = json.loads(m.get("message") or "")
        except Exception:
            continue
        if e.get("event") == "call_ended":
            ended = True
            break
        if e.get("event") == "function_call_start" and e.get("function") not in ("code_exec", "end_call"):
            args = e.get("args") or {}
            body = args.get("body") if isinstance(args.get("body"), dict) else args
            body = {k: v for k, v in body.items() if k not in ("customer_id", "url", "method", "headers")}
            name = e.get("function")
            if name == "api_call" and "get_account" in str(args.get("url")):
                name = "get_account"
            lines.append(f"[tool call {name} {json.dumps(body, sort_keys=True)}]")
        if e.get("event") == "function_call_complete" and e.get("function") not in ("code_exec", "end_call"):
            res = e.get("result") or {}
            data = res.get("data") if isinstance(res, dict) else None
            if isinstance(data, dict) and "ok" in data:
                lines.append(f"[tool result {e.get('function')} ok={data.get('ok')}" + (f" error={data.get('error')}" if data.get("error") else "") + "]")
        if e.get("event") == "function_call_error" and e.get("function") not in ("code_exec", "end_call"):
            # A failed call (the bank's 5xx) is its own event: show it, so a retry is seen as a retry.
            lines.append(f"[tool result {e.get('function')} FAILED: {str(e.get('error'))[:120]}]")
    return lines, ended


def call_ended(call_id):
    try:
        return trace(call_id)[1]
    except Exception:
        return False


JUDGE = """You judge a recorded phone call between a bank's collections AGENT and a CUSTOMER. Tool calls the agent made appear in
square brackets in order. Decide for each check whether it is true of the call, judging the substance as a fair reviewer would.
A check about something that only applies when a situation arises ("when asked") is true if that situation never arose.
Use the call's own date given below for any date reasoning, never today's date.
Answer with JSON only: {"checks": [{"check": "...", "true": true|false, "why": "short reason"}]}"""


def judge(case, lines):
    now = case["variables"].get("now", "")
    text = ("THE CALL TAKES PLACE AT: " + now + " (local time)\n\nCHECKS:\n- " + "\n- ".join(case["checks"])
            + "\n\nCALL:\n" + "\n".join(lines))
    raw = claude(JUDGE, text, "sonnet", timeout=180)
    try:
        raw = raw.replace(chr(92) + chr(39), chr(39))
        return json.JSONDecoder().raw_decode(raw[raw.index("{"):])[0]["checks"]
    except Exception:
        return [{"check": "judge", "true": False, "why": "no verdict: " + raw[:200]}]


def run_case(wid, case, style, outdir, tag):
    variables = http("/v1/practice/sessions", {"case": case["id"]})["variables"]
    persona = persona_for(case, {"identity": case["identity"]}, style)["prompt"]
    call_id, convo, msg, note = None, [], "Hello?", ""
    for turn in range(40):
        agent = None
        for attempt in range(3):
            try:
                agent, call_id = say(wid, variables, call_id, msg)
                break
            except Exception as e:
                note = str(e)[:160]
                if call_id and call_ended(call_id):
                    break
                time.sleep(5)
        if agent is None:
            break
        convo.append(("CUSTOMER", msg)); convo.append(("CALLER", agent))
        if call_id and re.search(r"goodbye|good bye|bye\b", agent, re.I) and call_ended(call_id):
            break
        transcript = "\n".join(f"{who}: {text}" for who, text in convo)
        msg = claude(persona, "CONVERSATION SO FAR (you are CUSTOMER, the bank is CALLER):\n" + transcript
                     + "\n\nWrite only your next line as CUSTOMER.", PERSONA_MODEL)
        msg = re.sub(r"^\s*CUSTOMER:\s*", "", msg).strip() or "Sorry?"
        if re.search(r"goodbye", msg, re.I) and call_id and call_ended(call_id):
            break
    try:
        freya.api("POST", "/api/v2/chat/end", {"callId": call_id})
    except Exception:
        pass
    time.sleep(2)
    led = http("/v1/practice/ledger/" + variables["customer_id"])
    r = score_ledger(case, led)
    try:
        lines, _ = trace(call_id)
    except Exception as e:
        lines = [f"(trace unavailable: {str(e)[:100]})"] + [f"{w}: {t}" for w, t in convo]
    checks = judge(case, lines)
    for c in checks:
        if not c.get("true"):
            r["failed"].append("check: " + str(c.get("check")) + " -- " + str(c.get("why"))[:200])
    r["pass"] = not r["failed"]
    tools = [x.get("tool") for x in led.get("calls", [])]
    # A platform error (5xx, "Agent service error") that cut the call before it closed says nothing about the agent.
    infra = bool(note) and not r["pass"] and "close_call" not in tools
    row = {"id": case["key"], "tag": tag, "pass": r["pass"], "infra": infra, "failed": r["failed"], "call_id": call_id,
           "tools": tools, "note": note}
    (outdir / f"{case['key']}-{tag}.txt").write_text("\n".join(lines) + "\n\n" + json.dumps(row, indent=1))
    with LOCK:
        print(("PASS" if r["pass"] else "INFRA" if infra else "FAIL"), case["key"], tag, call_id, flush=True)
        for f in r["failed"]:
            print("      -", f[:300], flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id"); ap.add_argument("--brief"); ap.add_argument("--only"); ap.add_argument("--cases", default="vendor/kit-v3/public-test-set.json")
    ap.add_argument("--reps", type=int, default=1); ap.add_argument("--style"); ap.add_argument("--workers", type=int, default=5); ap.add_argument("--out")
    ap.add_argument("--infra-retries", type=int, default=2)
    a = ap.parse_args()
    cases = [c for c in json.load(open(a.cases)) if (not a.brief or c["brief"] == a.brief) and (not a.only or c["id"] in a.only.split(","))]
    for c in cases:                       # variants reuse a public customer, so one id can name several cases
        same = [x for x in cases if x["id"] == c["id"]]
        c["key"] = c["id"] if len(same) == 1 else f"{c['id']}-v{same.index(c) + 1}"
    outdir = Path(a.out or f"chatrun-{time.strftime('%H%M%S')}")
    if outdir.suffix == ".json":
        outdir = outdir.with_suffix("")
    outdir.mkdir(parents=True, exist_ok=True)
    jobs = [(c, f"r{rep + 1}") for rep in range(a.reps) for c in cases]
    with ThreadPoolExecutor(a.workers) as pool:
        rows = list(pool.map(lambda j: run_case(a.workflow_id, j[0], a.style, outdir, j[1]), jobs))
        for again in range(a.infra_retries):          # runs a platform error cut short are run again
            redo = [i for i, row in enumerate(rows) if row["infra"]]
            if not redo:
                break
            time.sleep(60)
            fresh = list(pool.map(lambda i: run_case(a.workflow_id, jobs[i][0], a.style, outdir, jobs[i][1]), redo))
            for i, row in zip(redo, fresh):
                rows[i] = row
    by = {}
    for row in rows:
        if not row["infra"]:
            by.setdefault(row["id"], []).append(row["pass"])
    print()
    for cid, ps in by.items():
        print(("PASS" if all(ps) else "FAIL"), cid, f"{sum(ps)}/{len(ps)}")
    cut = sum(row["infra"] for row in rows)
    print(f"\n{sum(all(ps) for ps in by.values())} / {len(by)} cases pass every run"
          + (f" ({cut} runs cut short by platform errors are left out)" if cut else "") + f". Transcripts in {outdir}")
    (outdir / "summary.json").write_text(json.dumps({"workflow_id": a.workflow_id, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
