from builder.freya_client import Client
from builder.runtime import Budget


def test_publish_returns_published_version_and_exports_same_workflow(tmp_path):
    calls=[]
    workflow={"nodes":{"start":{}},"initial_node":"start"}
    def transport(method,path,body,params,timeout):
        calls.append((method,path))
        assert timeout <= 60
        if path=="/api/v2/workflow" and method=="POST":
            return {"workflow":{"id":"w1","agentId":"a1"}}
        if path=="/api/v2/workflow/w1" and method=="GET":
            return {"workflow":{"id":"w1","agentId":"a1","workflow":workflow}}
        if path=="/api/v2/versions/workflow/w1" and method=="GET":
            return {"versions":[{"id":"v2","versionNumber":2,"isPublished":False}]}
        return {}
    c=Client("unused",Budget(1800),workspace_id="ws",state_path=tmp_path/'state.json',transport=transport)
    deployment=c.publish("A-a",workflow)
    assert deployment["workflow_id"]=="w1" and deployment["version"]==2
    assert calls[-1]==("POST","/api/v2/versions/workflow/w1/publish")
    exported=c.export("w1")
    assert exported["workflow_id"]=="w1" and exported["workflow"]["nodes"]==workflow["nodes"]


def test_export_respects_remaining_total_deadline(tmp_path):
    clock=[0.0]
    budget=Budget(40,reserve=30,clock=lambda:clock[0])
    clock[0]=35
    observed=[]
    def transport(method,path,body,params,timeout):
        observed.append(timeout)
        return {"workflow":{"id":"w","workflow":{"nodes":{}}}}
    c=Client("unused",budget,workspace_id="ws",state_path=tmp_path/'state.json',transport=transport)
    c.export("w")
    assert 0 < observed[0] <= 5


def test_transient_errors_are_retried_but_client_errors_are_not(tmp_path, monkeypatch):
    from builder import freya_client
    monkeypatch.setattr(freya_client.time, "sleep", lambda s: None)
    calls = []
    def flaky(method, path, body, params, timeout):
        calls.append(path)
        if len(calls) < 3: raise freya_client.TransientError("503")
        return {"ok": True}
    c = Client("unused", Budget(1800), workspace_id="ws", state_path=tmp_path/'state.json', transport=flaky)
    assert c.api("GET", "/x") == {"ok": True} and len(calls) == 3
    def rejected(method, path, body, params, timeout):
        calls.append(path); raise RuntimeError("400")
    c = Client("unused", Budget(1800), workspace_id="ws", state_path=tmp_path/'state.json', transport=rejected)
    calls.clear()
    try: c.api("GET", "/y")
    except RuntimeError: pass
    assert len(calls) == 1


def test_an_unavailable_service_is_retried_while_the_budget_allows(tmp_path, monkeypatch):
    from builder import freya_client
    pauses = []
    monkeypatch.setattr(freya_client.time, "sleep", pauses.append)
    calls = []
    def down(method, path, body, params, timeout):
        calls.append(path)
        if len(calls) < 20: raise freya_client.Unavailable("503: API key validation is temporarily unavailable")
        return {"ok": True}
    c = Client("unused", Budget(1800), workspace_id="ws", state_path=tmp_path/'state.json', transport=down)
    assert c.api("GET", "/x") == {"ok": True} and len(calls) == 20 and max(pauses) == 30
    # A service that does not answer in time is retried the same way.
    calls.clear()
    def slow(method, path, body, params, timeout):
        calls.append(path)
        if len(calls) < 6: raise freya_client.Unreachable("Freya POST /api/v2/workflow unreachable: TimeoutError")
        return {"ok": True}
    c = Client("unused", Budget(1800), workspace_id="ws", state_path=tmp_path/'state.json', transport=slow)
    assert c.api("POST", "/x") == {"ok": True} and len(calls) == 6
    # With no time left for a pause, the error comes back at once.
    calls.clear()
    c = Client("unused", Budget(150), workspace_id="ws", state_path=tmp_path/'state.json', transport=down)
    try: c.api("GET", "/y")
    except freya_client.Unavailable: pass
    assert len(calls) == 1
