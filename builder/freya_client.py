"""Deadline-aware adaptation of the official v3 Freya client (same export format)."""
import json
import urllib.request
import urllib.parse
from pathlib import Path
from .runtime import write_json

AGENT_LLM = {"provider":"experimental-5", "model":"experimental-5"}


class Client:
    def __init__(self,key,budget,workspace_id=None,state_path=Path("runs/platform-state.json"),url="https://staging-app.freyavoice.ai",transport=None):
        if not key: raise ValueError("FREYA_API_KEY is missing")
        self.key,self.budget,self.workspace_id,self.state_path,self.url=key,budget,workspace_id,Path(state_path),url.rstrip('/')
        self.transport=transport

    def api(self,method,path,body=None,finalizing=False,**params):
        timeout=min(30,self.budget.require(1,finalizing=finalizing))
        if self.transport:
            return self.transport(method,path,body,params,timeout)
        query="?"+urllib.parse.urlencode(params) if params else ""
        request=urllib.request.Request(self.url+path+query,data=json.dumps(body).encode() if body is not None else None,method=method,headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json","User-Agent":"Mozilla/5.0 (build-the-builder)"})
        with urllib.request.urlopen(request,timeout=timeout) as response:
            result=json.load(response)
        if isinstance(result,dict) and result.get("success") is False:
            raise RuntimeError("Freya API rejected request: "+str(result.get("data",{}).get("message","unknown error"))[:500])
        return result.get("data",{}).get("result",result) if isinstance(result,dict) else result

    def workspace(self):
        if self.workspace_id: return self.workspace_id
        response=self.api("GET","/api/v2/workspaces")
        items=(response.get("workspaces") or response.get("items") or []) if isinstance(response,dict) else response
        if len(items)!=1: raise ValueError("Set FREYA_WORKSPACE_ID when account has multiple workspaces")
        self.workspace_id=items[0]["id"]
        return self.workspace_id

    def validate(self,workflow):
        return self.api("POST","/api/v2/workflow",{"name":"builder validation","workflow":workflow},dryRun="true")

    def publish(self,slot,workflow):
        workspace=self.workspace()
        state=json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        key=workspace+":"+slot
        if key not in state:
            created=self.api("POST","/api/v2/workflow",{"name":"builder "+slot,"workflow":workflow})["workflow"]
            state[key]={"workflow_id":created["id"],"agent_id":created["agentId"]}
            write_json(self.state_path,state)
        record=state[key]
        wid=record["workflow_id"]
        self.api("PUT",f"/api/v2/workflow/{wid}",{"workflow":workflow})
        stored=self.api("GET",f"/api/v2/workflow/{wid}",workspaceId=workspace)["workflow"]["workflow"]
        config=stored.get("agent_config") or {}
        llm=config.get("llmConfig") or {}
        if any(llm.get(k)!=v for k,v in AGENT_LLM.items()):
            config["llmConfig"]={**llm,**AGENT_LLM}
            self.api("PUT",f"/api/v2/workflow/{wid}",{"workflow":{**stored,"agent_config":config}})
        versions=self.api("GET",f"/api/v2/versions/workflow/{wid}",workspaceId=workspace)["versions"]
        newest=max(versions,key=lambda v:v["versionNumber"])
        if not newest.get("isPublished"):
            self.api("POST",f"/api/v2/versions/workflow/{wid}/publish",{"versionId":newest["id"]})
        record["version"]=newest["versionNumber"]
        write_json(self.state_path,state)
        return dict(record)

    def export(self,workflow_id):
        w=self.api("GET",f"/api/v2/workflow/{workflow_id}",workspaceId=self.workspace(),finalizing=True)["workflow"]
        return {"workflow_id":w["id"],"agent_id":w.get("agentId"),"updated_at":w.get("updatedAt"),"workflow":w["workflow"]}

    def call(self,call_id):
        return self.api("GET",f"/api/v2/call/{call_id}")["call"]

    def simulation_runs(self,simulation_id,iteration_id):
        return self.api("GET",f"/api/v2/simulations/{simulation_id}/iterations/{iteration_id}",limit=100,offset=0)
