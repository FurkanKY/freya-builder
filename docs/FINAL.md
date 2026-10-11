# Final runbook (Sunday 11 October 2026)

Times are Istanbul time (UTC+3). Briefs open at 20:00, submissions close at 23:00.

## Before 20:00
- `git status` is clean, and the commit to use carries the tag `final-candidate` (`git checkout final-candidate`, or stay on the branch head if it is the same commit).
- Tests pass: `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`.
- `submission/` holds no rehearsal files.
- No simulation is running in the workspace.
- `.env` sets `BUILDER_MODEL=claude-sonnet-5` (or leaves it out), never the bare alias `sonnet`: a Claude Code update can move the alias to another model, and every measured build used `claude-sonnet-5`. After each build, the `model_start` lines in the trace name `claude-sonnet-5`.
- The builder reads the brief through the `claude` CLI and its logged-in account, so that account's 5-hour usage limit must have room from 20:00 on. `scripts/chat_cases.py` uses the same account for its customer and its judge, and a full measurement can use up a whole window (seen Sunday 03:20: "You've hit your session limit"). The window is 5 hours from its first use: on Sunday one opened at 06:10 and a full measurement used it up by 07:30; the next opens at 11:10 and closes at 16:10. Use the CLI for nothing between 16:10 and 19:50, so the check at 19:50 opens a fresh window that lasts until 00:50: `claude -p --model claude-sonnet-5 "say ok"` answers with no limit message. `claude -p "/usage"` shows the account's session and weekly use and costs nothing (Sunday 07:47: weekly 48%, resets 16 October).
- The Claude desktop app session that runs this work uses the same account, so its own use opens a window too: on Sunday the next window opened at 16:10 and resets at 21:10 (3% used at 17:10). The app's usage card shows it. One build (three reads) used less than 1%, so the builds of 20:00–23:00 fit in that window and the one after it.

## For each final brief (slot final-1 for the first, final-2 for the second)
1. Put the brief files and the tool API file in a new folder `final/<n>/`, unchanged. `final/` is in `.gitignore`, so the tree stays clean and the trace's `build_start` line says `dirty: false` with the candidate's commit.
2. Build it, with no manual step:
   `.venv/bin/python -m builder.build --brief final/<n>/<brief files> --tool-api final/<n>/<api>.json --slot final-<n>`
   One build takes about a minute; the limit is 30 minutes per run. Run the builds one after the other: a build started while another runs stops at once ("Another builder process is running").
3. Each build reads the brief three times in parallel and keeps the read that agrees most with the other two. The `spec_vote` line in the trace lists the fields where the reads differ (`fields_that_differ`). When a decision field differs (deadline, attempts, floor, outcome codes, calendar, identity), run one more build and compare the specs:
   `.venv/bin/python scripts/spec_diff.py <run_id> <run_id>`
   The three reads of one build are in `runs/<run_id>/read-<k>/spec.json` and can be compared the same way.
   A `spec_still_invalid` line in the trace lists contract issues no fix read removed (for example an opening sentence the brief gives word for word that the spec does not say unchanged): read them, and run one more build when one names a decision field or the opening line.
   Read that part of the brief and submit the run whose spec matches it. The builder code is never edited with anything from the brief. Only a generic crash fix is allowed, for example a table shape the parser did not expect.
4. Submit the chosen run: `.venv/bin/python -m builder.submit <run_id> final-<n>`. This copies `final.workflow.json` (the `export_workflow` file) and that run's trace into `submission/`.

## At the end
- `submission/` holds `final-1.*` and `final-2.*`: workflow, trace.jsonl and trace.txt each.
- Scan for secrets: no API key from `.env` appears in `submission/` or in the trace.
- Submit the two workflow files, the code (this repository at the chosen commit) and the two traces before 23:00.
