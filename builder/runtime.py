"""Small, deterministic boundaries shared by the build and evaluation paths."""
import ast
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


class Budget:
    def __init__(self, seconds=1800, reserve=120, clock=time.monotonic):
        self.clock, self.reserve = clock, reserve
        self.end = clock() + seconds

    def remaining(self):
        return max(0, self.end - self.clock())

    def available(self):
        return max(0, self.remaining() - self.reserve)

    def require(self, seconds, finalizing=False):
        remaining = self.remaining() if finalizing else self.available()
        if remaining < seconds:
            raise TimeoutError("Insufficient build budget; preserve the last checkpoint")
        return remaining


class Trace:
    def __init__(self, path, secrets=()):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets = [s for s in secrets if s]

    def clean(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    def emit(self, event, **data):
        at = datetime.now(timezone.utc).isoformat()
        line = self.clean(json.dumps({"at": at, "event": event, **data}, ensure_ascii=False, default=str))
        with self.path.open("a") as handle:
            handle.write(line + "\n")
        # A plain-text twin for human readers: one line per event, long values shortened.
        parts = []
        for key, value in data.items():
            if key == "usage" and isinstance(value, dict):
                value = {k: value.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            parts.append(f"{key}={text if len(text) <= 300 else text[:300] + '...'}")
        with self.path.with_suffix(".txt").open("a") as handle:
            handle.write(self.clean(f"{at} {event}: " + ", ".join(parts)) + "\n")
        print(line, flush=True)


def load_inputs(briefs, api):
    documents = []
    for path in briefs:
        path = Path(path)
        # Raw bank material can come as mails, extracts or code lists in several text formats.
        kinds = (".md", ".txt", ".eml", ".csv", ".html", ".htm", ".rst")
        files = sorted(f for f in path.glob("**/*") if f.is_file() and f.suffix.lower() in kinds) if path.is_dir() else [path]
        if not files:
            raise ValueError("Brief directory contains no text files")
        for file in files:
            text = file.read_text()
            documents.append({"path": file.name, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    if not documents:
        raise ValueError("At least one brief is required")
    schema = json.loads(Path(api).read_text())
    if not schema.get("servers") or not isinstance(schema.get("paths"), dict):
        raise ValueError("Tool API must contain servers and paths")
    return {"briefs": documents, "api": schema, "fingerprint": digest({"briefs": documents, "api": schema})}


def walk(value, location="workflow"):
    if isinstance(value, dict):
        yield location, value
        for key, child in value.items():
            yield from walk(child, location + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{location}[{index}]")


def validate_workflow(workflow, api):
    from .spec import resolve_refs
    api = resolve_refs(api)
    issues = []
    nodes = workflow.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return ["workflow.nodes must be a nonempty object"]
    if workflow.get("initial_node") not in nodes:
        issues.append("initial_node does not exist")
    if "agent_config" in workflow:
        issues.append("agent_config must be omitted; the event controls the model")
    global_nodes = workflow.get("global_nodes", {})
    targets = set(nodes) | (set(global_nodes) if isinstance(global_nodes, dict) else set()) | {"__previous__"}
    from .spec import resolve_refs
    api = resolve_refs(api)
    allowed_urls = {s["url"].rstrip("/") + "/" + p.lstrip("/"): v for s in api.get("servers", []) for p, v in api.get("paths", {}).items()}
    for location, item in walk(workflow):
        # workflow-format.md: the top-level condition group always uses "or"; a mismatch fails silently.
        condition = item.get("condition")
        if isinstance(condition, dict) and "conditions" in condition and str(condition.get("logic")).lower() != "or":
            issues.append(f"{location}.condition: top-level logic must be or (nest and inside it)")
        for key in ("target_node", "passthrough_default_transition", "max_turn_transition"):
            if item.get(key) and item[key] not in targets:
                issues.append(f"{location}.{key}: missing target {item[key]}")
        if "function" not in item:
            continue
        function = item["function"]
        handler = function.get("handler", "")
        params = function.get("parameters", {}).get("properties", {})
        if handler == "__function__:api_call":
            url = params.get("url", {}).get("default")
            # A path parameter is filled as {{name}} and a call-variable query parameter is appended (compile.api_tool).
            key = re.sub(r"\{\{(\w+)\}\}", r"{\1}", url.split("?")[0]) if isinstance(url, str) else url
            if key not in allowed_urls:
                issues.append(f"{location}: HTTP URL is not in supplied OpenAPI: {url}")
            else:
                method = str(params.get("method", {}).get("default", "POST")).lower()
                operation = allowed_urls[key].get(method)
                if operation is None:
                    issues.append(f"{location}: HTTP method is not in OpenAPI")
                else:
                    body = params.get("body", {}).get("properties", {})
                    expected = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                    if "$ref" not in expected:
                        for field in expected.get("required", []):
                            if field not in body:
                                issues.append(f"{location}: missing required bank field {field}")
        elif handler == "__function__:code_exec":
            code = params.get("code", {}).get("default")
            if not isinstance(code, str):
                issues.append(f"{location}: Python source must be a baked string")
            else:
                try:
                    ast.parse(code)
                except SyntaxError as exc:
                    issues.append(f"{location}: invalid Python at line {exc.lineno}")
                if "{{" in code or "}}" in code:
                    issues.append(f"{location}: Python source contains unsafe template braces")
        elif handler not in {"__function__:end_call"}:
            issues.append(f"{location}: unsupported function handler {handler}")
        for hook in ("pre_process_code", "post_process_code"):
            if item.get(hook):
                try:
                    ast.parse(item[hook])
                except SyntaxError:
                    issues.append(f"{location}: invalid Python {hook}")
    return issues


def select_candidate(incumbent, challenger):
    if incumbent.get("status") != "completed" or challenger.get("status") != "completed":
        return "incumbent"
    if incumbent.get("suite") != challenger.get("suite"):
        return "incumbent"
    old, new = incumbent["case_passes"], challenger["case_passes"]
    if old.keys() != new.keys() or any(passed and not new[key] for key, passed in old.items()):
        return "incumbent"
    return "challenger" if sum(new.values()) > sum(old.values()) else "incumbent"
