from builder.freya_client import Client
from builder.runtime import Budget


def test_publish_returns_published_version_and_exports_same_workflow(tmp_path):
    calls=[]
    workflow={"nodes":{"start":{}},"initial_node":"start"}
    def transport(method,path,body,params,timeout):
        calls.append((method,path))
        assert timeout <= 30
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
