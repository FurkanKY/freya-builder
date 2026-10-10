from builder.evaluate import summarize, assert_public_suite
import pytest


def test_all_repetitions_must_pass():
    report={"runs":3,"final":[{"id":"a","passes":2,"runs":3,"pass":False},{"id":"b","passes":3,"runs":3,"pass":True}]}
    result=summarize(report,"suite")
    assert result["passed"] == 1
    assert result["case_passes"] == {"a":False,"b":True}


def test_public_suite_rejects_modified_brief(tmp_path):
    (tmp_path/'briefs').mkdir()
    (tmp_path/'briefs/brief-a.md').write_text('original')
    with pytest.raises(ValueError):
        assert_public_suite([{"text":"modified"}], "A", tmp_path)


def test_persona_map_is_shared_between_runs(tmp_path, monkeypatch):
    import json, subprocess
    from builder.evaluate import run_evaluation
    from builder.runtime import Budget, Trace
    kit = tmp_path/'kit'; (kit/'tools').mkdir(parents=True)
    (kit/'public-test-set.json').write_text(json.dumps([{"id":"PUB-01","brief":"A"}]))
    (kit/'tools/run_cases.py').write_text("")
    shared = tmp_path/'runs/personas.json'; shared.parent.mkdir(); shared.write_text('{"old":"p0"}')
    class Done:
        returncode = 0
        def __init__(self, command, cwd, **kw):
            assert json.loads((cwd/'.personas.json').read_text()) == {"old":"p0"}
            (cwd/'.personas.json').write_text('{"old":"p0","new":"p1"}')
            out = command[command.index('--out')+1]
            open(out,'w').write(json.dumps({"final":[{"id":"PUB-01","passes":1,"runs":1}]}))
        def poll(self): return 0
    monkeypatch.setattr(subprocess, 'Popen', Done)
    run_evaluation('agent', 'A', kit, tmp_path/'test-a', Budget(1800), Trace(tmp_path/'t.jsonl'), {}, personas=shared)
    assert json.loads(shared.read_text()) == {"old":"p0","new":"p1"}
