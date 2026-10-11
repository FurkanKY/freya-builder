"""Lenient reading of a model's JSON answer: a long answer sometimes drops a closing bracket or leaves a trailing comma."""
import json
import re


def _strip_fence(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0] if "```" in text else text
    return text.strip()


def _unclosed(text):
    """The brackets still open at the end of text, outside strings, in opening order."""
    stack, in_string, escaped = [], False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    return stack, in_string


def _hoist(data, keys):
    """A top-level key that a dropped bracket pushed into the last nested object is moved back to the top."""
    if not isinstance(data, dict):
        return data
    for key in keys:
        if key in data:
            continue
        node = data
        for _ in range(4):
            last = next(reversed(node.values()), None) if node else None
            if not isinstance(last, dict):
                break
            if key in last:
                data[key] = last.pop(key)
                break
            node = last
    return data


def _close(body):
    body = re.sub(r",(\s*[}\]])", r"\1", body).rstrip().rstrip("`").rstrip()
    stack, in_string = _unclosed(body)
    if in_string:
        body += '"'
    body = re.sub(r",\s*$", "", body)
    return body + "".join("}" if ch == "{" else "]" for ch in reversed(stack)), len(stack)


def _rank(data, keys, score):
    if not isinstance(data, dict):
        return (1, 1 << 30)
    return (sum(1 for k in keys if k not in data), score(data) if score else 0)


def loads_object(text, keys=(), score=None):
    """The JSON object in a model answer. On a syntax error, trailing commas are dropped and the brackets the answer left
    open are closed. Where a bracket was dropped mid-answer, each line end is tried as its place and the reading whose
    top-level keys (keys) are all present and whose score(data) (count of structural problems) is lowest wins; keys that
    still ended up nested are hoisted. Raises ValueError when nothing parses."""
    text = _strip_fence(text)
    start = text.find("{")
    if start < 0:
        raise ValueError("output holds no JSON object")
    end = text.rfind("}")
    try:
        data = json.loads(text[start:end + 1], strict=False)
    except json.JSONDecodeError as first:
        body = text[start:]
        best, best_rank = None, None
        closed, missing = _close(body)
        try:
            best = json.loads(closed, strict=False)
            best_rank = _rank(best, keys, score)
        except json.JSONDecodeError:
            pass
        if missing and (best is None or best_rank != (0, 0)):
            # One closer at a time: put it at the end of a line that ends a value, close the rest at the end.
            for match in re.finditer(r'(?<=[}\]"\deltrue])[ \t]*(?=,?[ \t]*\n)', body):
                for closer in "}]":
                    trial, _ = _close(body[:match.start()] + closer + body[match.start():])
                    try:
                        data = json.loads(trial, strict=False)
                    except json.JSONDecodeError:
                        continue
                    rank = _rank(data, keys, score)
                    if best_rank is None or rank < best_rank:
                        best, best_rank = data, rank
        if best is None:
            raise ValueError(f"output is not valid JSON: {first}") from first
        data = _hoist(best, keys)
    if not isinstance(data, dict):
        raise ValueError("output is not a JSON object")
    return data
