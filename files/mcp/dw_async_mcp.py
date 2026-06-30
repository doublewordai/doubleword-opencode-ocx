#!/usr/bin/env python3
"""
Doubleword ASYNC (flex) as an MCP tool for opencode.

Three tools are exposed:

1. doubleword_async (PRIMARY)
   Blocking path: calls the flex tier and returns the text.  Most requests finish in
   under a minute, so this is the fastest, simplest, default choice.  Only avoid it
   if you know the upstream flex queue is extremely long and you cannot afford the
   wait within the current turn.

2. submit_async_job (FALLBACK)
   Non-blocking path: returns a job_id instantly, then runs the request in a
   background thread.  Use this when the user explicitly says they do not want to
   wait, or when a previous doubleword_async call has timed out and the user still
   wants the work done.

3. get_async_result (FALLBACK COMPANION)
   Poll the result of a job_id previously created by submit_async_job.

stdlib only (no pip installs).  DOUBLEWORD_API_KEY is passed via the MCP environment
block in opencode config.  Logs to stderr; stdout carries JSON-RPC only.
"""
import sys, json, os, urllib.request, threading, time, uuid

UPSTREAM = "https://api.doubleword.ai/v1/chat/completions"
JOB_TTL_SECONDS = 7200
LAST_CLEANUP = 0

_lock = threading.Lock()
JOBS: dict[str, dict] = {}

def log(*a): print("[dw-async-mcp]", *a, file=sys.stderr, flush=True)

def _cleanup_expired():
    """Purge stale job records."""
    global LAST_CLEANUP
    now = time.time()
    if now - LAST_CLEANUP < 60:
        return
    LAST_CLEANUP = now
    with _lock:
        stale = [jid for jid, rec in JOBS.items() if rec["expires_at"] < now]
        for jid in stale:
            JOBS.pop(jid, None)
        if stale:
            log("cleanup: purged", len(stale), "expired job(s)")

def _run_flex(job_id: str, prompt: str, model: str, max_tokens: int):
    """Worker thread: call the flex API and write the result back into JOBS."""
    key = os.environ.get("DOUBLEWORD_API_KEY", "")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "service_tier": "flex", "max_tokens": max_tokens, "stream": False}
    try:
        req = urllib.request.Request(UPSTREAM, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as resp:
            payload = json.loads(resp.read())
        m = (payload.get("choices") or [{}])[0].get("message", {}) or {}
        text = (m.get("content") or m.get("reasoning") or m.get("reasoning_content") or "(empty)").strip()
        with _lock:
            JOBS[job_id] = {"status": "done", "result": text, "error": "",
                            "expires_at": time.time() + JOB_TTL_SECONDS}
    except Exception as e:
        log("ERROR job", job_id, repr(e))
        with _lock:
            JOBS[job_id] = {"status": "error", "result": "", "error": str(e),
                            "expires_at": time.time() + JOB_TTL_SECONDS}

def flex(prompt: str, model: str, max_tokens: int = 4000) -> str:
    """Blocking synchronous call to Doubleword's flex tier; returns the model text."""
    key = os.environ.get("DOUBLEWORD_API_KEY", "")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "service_tier": "flex", "max_tokens": max_tokens, "stream": False}
    req = urllib.request.Request(UPSTREAM, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as resp:
        payload = json.loads(resp.read())
    m = (payload.get("choices") or [{}])[0].get("message", {}) or {}
    return (m.get("content") or m.get("reasoning") or m.get("reasoning_content") or "(empty)").strip()

def _submit_job(prompt: str, model: str, max_tokens: int = 4000) -> str:
    job_id = "dw_" + uuid.uuid4().hex[:16]
    with _lock:
        JOBS[job_id] = {"status": "pending", "result": "", "error": "",
                         "expires_at": time.time() + JOB_TTL_SECONDS}
    t = threading.Thread(target=_run_flex, args=(job_id, prompt, model, max_tokens), daemon=True)
    t.start()
    return job_id

def _get_result(job_id: str) -> dict:
    with _lock:
        rec = JOBS.get(job_id)
    if rec is None:
        return {"status": "not_found", "result": "", "error": "job_id does not exist or has expired"}
    return rec

TOOLS = [{
    "name": "doubleword_async",
    "description": "Run a prompt on Doubleword's ASYNC (flex) tier and return the model text. This is the default tool for async completions: most jobs finish quickly enough to wait for. Use this unless the downstream queue is extremely long and you want to avoid blocking the current turn.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "prompt":  {"type": "string"},
            "model":   {"type": "string", "description": "default moonshotai/Kimi-K2.6"},
            "max_tokens": {"type": "integer", "description": "default 4000"}
        },
        "required": ["prompt"]
    }
}, {
    "name": "submit_async_job",
    "description": "Submit a prompt to Doubleword's ASYNC (flex) tier and receive a job_id immediately without waiting for the response. Use this ONLY as a fallback when the user explicitly does not want to wait or when a previous doubleword_async call timed out and the user still wants the work completed. After submitting, the user must later ask you to check the job (using get_async_result with the job_id).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "prompt":  {"type": "string", "description": "The prompt to send to the flex model."},
            "model":   {"type": "string", "description": "Model ID (default: moonshotai/Kimi-K2.6)."},
            "max_tokens": {"type": "integer", "description": "Maximum tokens (default: 4000)."}
        },
        "required": ["prompt"]
    }
}, {
    "name": "get_async_result",
    "description": "Check the status and result of a previously created async job. Returns immediately with pending / done / error / not_found. Use this ONLY after calling submit_async_job, and only when the user explicitly asks you to check on the job.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job_id returned by submit_async_job."}
        },
        "required": ["job_id"]
    }
}]

def _make_text(text: str):
    return {"type": "text", "text": text}

def handle(msg: dict):
    _cleanup_expired()
    mid, method = msg.get("id"), msg.get("method")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "doubleword-async", "version": "0.2.1"}}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = msg.get("params") or {}
        args = params.get("arguments") or {}
        tool_name = (params.get("name") or "").strip()

        try:
            if tool_name == "doubleword_async":
                text = flex(
                    args.get("prompt", ""),
                    args.get("model") or "moonshotai/Kimi-K2.6",
                    int(args.get("max_tokens", 4000))
                )
                return {"jsonrpc": "2.0", "id": mid, "result": {"content": [_make_text(text)], "isError": False}}

            if tool_name == "submit_async_job":
                job_id = _submit_job(
                    args.get("prompt", ""),
                    args.get("model") or "moonshotai/Kimi-K2.6",
                    int(args.get("max_tokens", 4000))
                )
                out = json.dumps({"job_id": job_id, "status": "submitted"})
                return {"jsonrpc": "2.0", "id": mid, "result": {"content": [_make_text(out)], "isError": False}}

            if tool_name == "get_async_result":
                rec = _get_result(args.get("job_id", ""))
                out = json.dumps(rec)
                return {"jsonrpc": "2.0", "id": mid, "result": {"content": [_make_text(out)], "isError": False}}

            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"tool not found: {tool_name}"}}

        except Exception as e:
            log("ERROR handling tool call:", repr(e))
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [_make_text(f"error: {e}")], "isError": True}}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}

    return None

def main():
    log("server started (v0.2.1)")
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
            sys.stdout.write(json.dumps(r) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
