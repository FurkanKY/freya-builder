import json
import pytest
from builder.runtime import digest
from builder.submit import submit


def make_run(root, status="validated", tamper=False):
    run = root/"runs"/"r1"; run.mkdir(parents=True)
    export = {"workflow_id": "w", "agent_id": "a", "updated_at": "t", "workflow": {"nodes": {}}}
    (run/"final.workflow.json").write_text(json.dumps(export))
    (run/"trace.jsonl").write_text("{}\n"); (run/"trace.txt").write_text("x\n")
    (run/"result.json").write_text(json.dumps({"status": status, "export_sha256": "bad" if tamper else digest(export)}))


def test_submit_copies_export_and_traces(tmp_path):
    make_run(tmp_path)
    out = submit("r1", "final-1", root=tmp_path)
    assert out["files"] == ["final-1.trace.jsonl", "final-1.trace.txt", "final-1.workflow.json"]


def test_submit_refuses_failed_or_mismatched_runs(tmp_path):
    make_run(tmp_path, status="failed")
    with pytest.raises(ValueError):
        submit("r1", "x", root=tmp_path)
    other = tmp_path/"o"; other.mkdir()
    make_run(other, tamper=True)
    with pytest.raises(ValueError):
        submit("r1", "x", root=other)
