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
