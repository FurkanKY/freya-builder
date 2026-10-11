# Final runbook (Sunday 11 October 2026)

Times are Istanbul time (UTC+3). The case opens at 20:00, submissions close at 23:00.

The final case is one zip: a folder of Markdown, Word, PDF and Excel documents, a service contract (prose or OpenAPI),
test customers and example conversations. We serve the contract from our own mock on Cloudflare Workers, and the
builder turns the folder into a published Freya workflow whose tools call that mock.

## Before 20:00
- The commit to use carries the tag `final-candidate`, and the tests pass:
  `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`.
- `final/`, `traces/` and `submission/` hold no rehearsal files. No simulation is running in the workspace.
- `.env` sets `BUILDER_MODEL=claude-sonnet-5` (or leaves it out), never the bare alias `sonnet`. After each build the
  `model_start` lines in the trace name `claude-sonnet-5`.
- The builder reads the case through the `claude` CLI and its logged-in account, so that account's 5-hour usage window
  must have room from 20:00 on: `claude -p --model claude-sonnet-5 "say ok"` answers with no limit message. One build
  (one contract read and three spec reads) uses about 1% of a window.
- The mock skeleton (`mock/`) is deployed at `https://freya-bank-mock.fky-freya.workers.dev` (`/__health` answers).
  Its URL is fixed before the case opens, so the build can start before the mock is filled in.

## At 20:00
1. Unzip the case unchanged into `final/` (drop `__MACOSX`). `final/` is in `.gitignore`, so the build's
   `build_start` line says `dirty: false` with the candidate's commit.
2. Start the build at once:
   `.venv/bin/python builder/build.py final/<Folder>/ https://freya-bank-mock.fky-freya.workers.dev 2>&1 | tee traces/final-1.log`
   - `case_documents` lists every file read and every file skipped.
   - `case_read` gives the role of each document (only the policy documents reach the phone agent's prompt; test
     customers and example conversations do not), the operation each of the seven roles maps to, and the extra tools.
   - The contract's OpenAPI (derived from prose when needed) is in `runs/<run_id>/case/openapi.json`, with its
     servers pointing at the mock URL plus the contract's base path.
   - `spec_vote` lists the fields where the three reads differ; `spec_still_invalid` lists contract issues no read fixed.
3. Meanwhile fill the mock from `runs/<run_id>/case/openapi.json` and the test customers (`mock/tools/xlsx2json.py`
   for Excel), run `node test/run.mjs` and the replay of the example conversations (`mock/tools/replay.mjs`), deploy
   with `npx wrangler deploy` in `mock/`, and call every operation once with `curl`.
4. Check the published agent: every tool URL starts with the mock URL and holds no literal `{...}`; the agent speaks the
   case's language; the opening is the case's own sentence; one chat call with a test customer reaches the expected
   outcome in the mock's `/__state`. Reset the mock with `POST /__reset` before and after.
5. Rebuild only for a generic bug fix in the builder (never with anything from the case), with a new log
   (`traces/final-2.log`, ...). The builder code is never edited with case content.

## At the end
- Copy the chosen run's log to `traces/final.log` and its `final.workflow.json` to `submission/final.workflow.json`.
- Scan for secrets: no API key from `.env` appears in `submission/`, `traces/` or the mock source.
- Commit and push; write `submission.json` (team, members, repo, commit, run_command, workflow, trace, mock_url) with
  `run_command` = `.venv/bin/python builder/build.py {case_folder} {mock_url}`.
- The repository must be readable by the organizers (public, or shared with them) before the email is sent.
- Send `submission.json` before 23:00 to the address of the kit email. The mock stays up until results are out.
