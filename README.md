# Freya Builder

Python coordinator using Claude Agent SDK and the official Freya v3 kit.
The builder uses the existing Claude Code login. The phone agent uses the event model.

How it works: one tool-less Claude call reads the briefs and the tool API and returns a
BankSpec (rules register, calendar, bands, identity questions, outcomes, phase checklists).
`builder/compile.py` turns it into a Freya workflow with verified platform patterns; the
briefs are embedded verbatim, dates and per-product deadlines are computed by a code node
(`builder/snippets/facts.py`), and the account is gated behind identity verification.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cp .env.example .env
```

Set `FREYA_API_KEY`, a persistent `FREYA_BANK_TEAM_KEY` of at least 16 characters,
and optionally `BUILDER_MODEL` (default `claude-sonnet-5`; keep the full model id, since a
Claude Code update can move the `sonnet` alias to another model). Never commit `.env`.
Authenticate Claude Code normally.

## Build

```bash
.venv/bin/python -m builder.build vendor/kit-v3/briefs/brief-a.md vendor/kit-v3/tools/openapi.json --slot public-a --suite A --only PUB-01,PUB-02,PUB-10
```

Multiple briefs use repeated flags (or positional brief paths before the API file):

```bash
.venv/bin/python -m builder.build --brief vendor/kit-v3/briefs/brief-a.md --brief vendor/kit-v3/briefs/brief-b.md --tool-api vendor/kit-v3/tools/openapi.json --slot public-b --suite B
```

Suite `AB` tests the A+B agent on all 13 public cases (Brief B keeps every Brief A rule).
Development measurements with repetitions or styles run outside the build budget:

```bash
.venv/bin/python -m builder.campaign <run_id> --suite AB --reps 3 --style pieces
```

For unseen briefs omit `--suite` unless an appropriate documented evaluation integration
is available. This produces a platform-validated export, **not a measured pass rate**.
`--repair` enables at most one behavior repair when enough time remains to retest it.
The official public tests are accepted only with their exact corresponding briefs and API.

Each run writes `runs/<id>/trace.jsonl`, candidate JSON, platform exports, official test
logs, and `result.json`. `runs/latest.json` points to the last run. A failed run may leave
a recoverable candidate export, but is never reported as a successful submission.

## Final briefs

One run per brief, no manual step, no `--suite` (the public tests do not match unseen briefs):

```bash
.venv/bin/python -m builder.build --brief <final-brief.md> --tool-api <final-openapi.json> --slot final-1
.venv/bin/python -m builder.submit <run_id> final-1
```

`builder.submit` checks that the run ended with an export whose hash matches `result.json` and
copies `final-1.workflow.json` (the `freya.export_workflow` format), `final-1.trace.jsonl` and the
plain-text `final-1.trace.txt` into `submission/`. Use a different `--slot` for each brief so the
two agents never overwrite each other. Raw bank material in several files is passed as repeated
`--brief` flags or as one directory.

## Tests

```bash
PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

Plugin autoload is disabled to isolate the project from system ROS pytest plugins.
The immutable kit lives in `vendor/kit-v3`; public tests run from a writable run copy.
Read `docs/PROGRESS.md` before resuming. A killed local test process does not imply its
Freya simulation stopped: inspect platform state before starting another simulation.
