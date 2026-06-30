#!/usr/bin/env python3
"""
Doubleword ASYNC (flex) as an MCP tool for opencode.

Why a tool: flex now streams SSE, so flex also works as a plain provider/model (doubleword-flex).
This tool is the complementary path — fire a discrete async job and get the result back as a tool
result (handy from any model/agent, without switching the whole turn to flex).

stdlib only (no pip installs). Reads the key from DOUBLEWORD_API_KEY (passed via the mcp
"environment" block in opencode config). Logs to stderr; stdout carries JSON-RPC only.
"""
import sys, json, os, urllib.request

UPSTREAM = "https://api.doubleword.ai/v1/chat/completions"

def log(*a): print("[dw-async-mcp]", *a, file=sys.stderr, flush=True)

def flex(prompt, model="moonshotai/Kimi-K2.6", max_tokens=4000):
    key = os.environ["DOUBLEWORD_API_KEY"]
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "service_tier": "flex", "max_tokens": max_tokens, "stream": False}
    req = urllib.request.Request(UPSTREAM, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    m = (json.loads(urllib.request.urlopen(req, timeout=900).read()).get("choices") or [{}])[0].get("message", {}) or {}
    return (m.get("content") or m.get("reasoning") or m.get("reasoning_content") or "(empty)").strip()

TOOLS = [{
    "name": "doubleword_async",
    "description": "Run a prompt on Doubleword's ASYNC (flex) tier: slower (seconds to minutes) but cheaper. For non-urgent, self-contained completions where latency is acceptable. Returns the model's text.",
    "inputSchema": {"type": "object",
        "properties": {"prompt": {"type": "string"},
                       "model": {"type": "string", "description": "default moonshotai/Kimi-K2.6"}},
        "required": ["prompt"]},
}]

def handle(msg):
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "doubleword-async", "version": "0.1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        a = (msg.get("params") or {}).get("arguments") or {}
        try:
            t = flex(a.get("prompt", ""), a.get("model") or "moonshotai/Kimi-K2.6")
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": t}], "isError": False}}
        except Exception as e:
            log("ERROR", repr(e))
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None

def main():
    log("server started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        r = handle(msg)
        if r is not None:
            sys.stdout.write(json.dumps(r) + "\n"); sys.stdout.flush()

if __name__ == "__main__":
    main()
