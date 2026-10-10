from builder.build import parse_args
import pytest


def test_positional_and_flag_cli_have_same_inputs():
    a=parse_args(['a.md','api.json'])
    b=parse_args(['--brief','a.md','--tool-api','api.json'])
    assert a.brief==b.brief==['a.md']
    assert a.tool_api==b.tool_api=='api.json'


def test_time_limit_cannot_exceed_competition_limit():
    with pytest.raises(SystemExit): parse_args(['a.md','api.json','--seconds','1801'])
