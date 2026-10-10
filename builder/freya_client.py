"""Deadline-aware adaptation of the official v3 Freya client (same export format)."""
import json
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from .runtime import write_json

class TransientError(RuntimeError):
    pass


class Unavailable(TransientError):
    """The service answered that it cannot take requests now (429, 502, 503, 504): the request was not run."""


AGENT_LLM = {"provider":"experimental-5", "model":"experimental-5"}


class Client:
    def __init__(self,key,budget,workspace_id=None,state_path=Path("runs/platform-state.json"),url="https://staging-app.freyavoice.ai",transport=None):
        if not key: raise ValueError("FREYA_API_KEY is missing")
        self.key,self.budget,self.workspace_id,self.state_path,self.url=key,budget,workspace_id,Path(state_path),url.rstrip('/')
        self.transport=transport
        # Set while publishing the first candidate: those calls may use the finalize reserve.
        self.finalizing=False

    def api(self,method,path,body=None,finalizing=False,**params):
        # Transient failures (5xx, dropped connections, timeouts) get two more tries; 4xx never retries.
        # A service that says it is unavailable is retried as long as the budget leaves time, with a growing
        # pause: an outage of some minutes then costs build time instead of the build.
        attempt=0
        while True:
            try:
                return self._api(method,path,body,finalizing,params)
            except Unavailable:
                attempt+=1
                pause=min(30,2*attempt)
                left=self.budget.remaining() if finalizing or self.finalizing else self.budget.available()
                if left<pause+30: raise
                time.sleep(pause)
            except TransientError:
                attempt+=1
                if attempt>=3 or self.budget.available()<10: raise
                time.sleep(2*attempt)

    def _api(self,method,path,body,finalizing,params):
        timeout=min(30,self.budget.require(1,finalizing=finalizing or self.finalizing))
        if self.transport:
            return self.transport(method,path,body,params,timeout)
        query="?"+urllib.parse.urlencode(params) if params else ""
        request=urllib.request.Request(self.url+path+query,data=json.dumps(body).encode() if body is not None else None,method=method,headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json","User-Agent":"Mozilla/5.0 (build-the-builder)"})
        try:
            with urllib.request.urlopen(request,timeout=timeout) as response:
                result=json.load(response)
        except urllib.error.HTTPError as exc:
            detail=f"Freya {method} {path} -> {exc.code}: {exc.read().decode(errors='replace')[:800]}"
            if exc.code in (429,502,503,504): raise Unavailable(detail) from None
            if exc.code>=500: raise TransientError(detail) from None
            raise RuntimeError(detail) from None
        except (urllib.error.URLError,TimeoutError,ConnectionError) as exc:
            raise TransientError(f"Freya {method} {path} unreachable: {type(exc).__name__}") from None
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
