"""Parameter templating: {{trigger.x}} and {{nodes.<id>.output.<path>}} resolved against persisted state only."""
from typing import Any

from core.platform.validation import REF


def resolve_params(params: dict, inputs: dict, outputs: dict[str, dict]) -> dict:
    def lookup(path: str) -> Any:
        parts = path.split(".")
        if parts[0] == "trigger":
            cur: Any = inputs
            rest = parts[1:]
        else:  # nodes.<id>.output.<field...>
            cur = outputs.get(parts[1])
            if cur is None:
                raise KeyError(f"node '{parts[1]}' has no output")
            rest = parts[3:]
        for key in rest:
            if isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
                cur = cur[int(key)]
                continue
            if not isinstance(cur, dict) or key not in cur:
                raise KeyError(f"'{path}' is not available")
            cur = cur[key]
        return cur

    def sub(value: Any) -> Any:
        if isinstance(value, str):
            whole = REF.fullmatch(value.strip())
            if whole:
                return lookup(whole.group(1))
            return REF.sub(lambda m: str(lookup(m.group(1))), value)
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sub(v) for v in value]
        return value

    return sub(params)


def coerce_param_types(spec, params: dict) -> dict:
    out = dict(params)
    for p in spec.params:
        if p.name not in out:
            if p.default is not None:
                out[p.name] = p.default
            continue
        v = out[p.name]
        if p.type == "number":
            out[p.name] = float(v)
        elif p.type == "boolean" and not isinstance(v, bool):
            out[p.name] = str(v).lower() == "true"
        elif p.type == "string" or p.type == "text":
            out[p.name] = str(v)
    return out
