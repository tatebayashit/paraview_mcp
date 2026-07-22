"""promptfoo custom provider: drives the paraview-mcp server as an agent
(docs/M3_PLAN.md E-01).

Per eval case, this provider:
  1. launches the MCP server (`python -m paraview_mcp.server`) over stdio,
  2. exposes its tools to an OpenRouter-hosted LLM (OpenAI-compatible
     chat/completions with function calling),
  3. runs the tool-call loop until the model answers or the call budget
     is exhausted,
  4. returns the final answer plus a compact tool trace (the trace lets
     assertions check *how* the model worked, not just what it said).

The server's FastMCP `instructions` are injected into the system prompt --
that coupling is the whole point: the eval measures instructions quality
(docs/M3_PLAN.md 3.2).

The bridge (pvpython standalone or a live GUI) must already be listening
on PARAVIEW_MCP_PORT before running -- see eval/README.md.

The eval model has no image input (deepseek-v4-flash is text->text), so
screenshots are replaced by a Pillow-computed text summary (dimensions +
fraction of non-background pixels), enough to judge "something rendered"
without vision (docs/M3_PLAN.md 1.4-5).
"""
import asyncio
import base64
import io
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "eval" / "data"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

MAX_TOOL_RESULT_CHARS = 6000
MAX_TRACE_ARG_CHARS = 300
MAX_TRACE_RESULT_CHARS = 250

SYSTEM_TEMPLATE = """\
You are an assistant controlling a running ParaView instance through MCP tools.

Server instructions (follow them):
{instructions}

Notes for this environment:
- Data files referenced by tasks live under: {data_root}
- Screenshots cannot be shown to you as images; instead you receive a text \
summary (dimensions and the fraction of pixels that differ from the dominant \
background color). Treat a non-trivial fraction (>2%) as "something is rendered".
"""


def _summarize_image(b64_data, mime_type):
    """Text stand-in for an image the model can't see: size + how much of
    the frame differs from the dominant (background) color."""
    try:
        from PIL import Image
        raw = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(raw))
        img.load()
        width, height = img.size
        thumb = img.convert("RGB").resize((64, 64))
        colors = thumb.getcolors(64 * 64)  # [(count, rgb)] -- never None at this size
        background = max(colors)[1]
        def near(a, b):
            return sum(abs(x - y) for x, y in zip(a, b)) < 30
        differing = sum(count for count, c in colors if not near(c, background))
        pct = 100.0 * differing / (64 * 64)
        return ("[screenshot: %dx%d px %s, %.1f%% of pixels differ from the "
                "dominant background color]" % (width, height, mime_type, pct))
    except Exception as e:  # never let image analysis kill the eval
        return "[screenshot received but could not be analyzed: %s]" % e


def _render_tool_result(result):
    """Flatten an MCP CallToolResult into text for the model."""
    parts = []
    for item in result.content:
        kind = getattr(item, "type", None)
        if kind == "text":
            text = item.text
            if len(text) > MAX_TOOL_RESULT_CHARS:
                text = text[:MAX_TOOL_RESULT_CHARS] + "...(truncated by eval harness)"
            parts.append(text)
        elif kind == "image":
            parts.append(_summarize_image(item.data, getattr(item, "mimeType", "")))
        else:
            parts.append("[unsupported content type: %r]" % kind)
    text = "\n".join(parts) if parts else "(empty result)"
    if getattr(result, "isError", False):
        text = "[tool returned error]\n" + text
    return text


def _mcp_tools_to_openai(tools):
    return [{
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description or "",
            "parameters": t.inputSchema or {"type": "object", "properties": {}},
        },
    } for t in tools]


class _OpenRouterClient:
    def __init__(self, model, temperature, max_tokens, timeout_s):
        import httpx
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set (export it from env/APIkey.env; "
                "see eval/README.md)")
        self._http = httpx.Client(timeout=timeout_s)
        self._headers = {"Authorization": "Bearer " + api_key}
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.usage = {"prompt": 0, "completion": 0, "total": 0}

    def chat(self, messages, tools, tool_choice="auto"):
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        last_error = None
        for attempt in range(3):
            resp = self._http.post(OPENROUTER_URL, json=body, headers=self._headers)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices")
                if not choices:
                    # OpenRouter sometimes answers 200 with an upstream-provider
                    # error body (e.g. {"error": {...}}) instead of "choices" --
                    # treat like a retryable server error rather than letting an
                    # unchecked KeyError blow up the caller.
                    last_error = "HTTP 200 with no choices: %s" % json.dumps(data)[:500]
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue
                usage = data.get("usage") or {}
                self.usage["prompt"] += usage.get("prompt_tokens", 0)
                self.usage["completion"] += usage.get("completion_tokens", 0)
                self.usage["total"] += usage.get("total_tokens", 0)
                return choices[0]["message"]
            last_error = "HTTP %s: %s" % (resp.status_code, resp.text[:500])
            if resp.status_code in (429, 500, 502, 503):
                import time
                time.sleep(2 * (attempt + 1))
                continue
            break
        raise RuntimeError("OpenRouter request failed: %s" % last_error)

    def close(self):
        self._http.close()


def _trace_line(index, name, arguments, ok, snippet):
    args = json.dumps(arguments, ensure_ascii=False)
    if len(args) > MAX_TRACE_ARG_CHARS:
        args = args[:MAX_TRACE_ARG_CHARS] + "..."
    snippet = " ".join(snippet.split())
    if len(snippet) > MAX_TRACE_RESULT_CHARS:
        snippet = snippet[:MAX_TRACE_RESULT_CHARS] + "..."
    return "%d. %s(%s) -> %s | %s" % (index, name, args, "ok" if ok else "ERROR", snippet)


async def _run_case(prompt, config):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    model = config.get("model") or os.environ.get("PARAVIEW_EVAL_MODEL", DEFAULT_MODEL)
    max_tool_calls = int(config.get("max_tool_calls", 15))
    temperature = float(config.get("temperature", 0))
    max_tokens = int(config.get("max_tokens", 4096))
    llm = _OpenRouterClient(model, temperature, max_tokens,
                            timeout_s=float(config.get("request_timeout_s", 180)))

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paraview_mcp.server"],
        cwd=str(REPO_ROOT),
        env=dict(os.environ),
    )
    trace = []
    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                instructions = (init.instructions or "").strip() or "(none provided)"
                tools = _mcp_tools_to_openai((await session.list_tools()).tools)

                messages = [
                    {"role": "system", "content": SYSTEM_TEMPLATE.format(
                        instructions=instructions, data_root=DATA_ROOT)},
                    {"role": "user", "content": prompt},
                ]
                final_text = ""
                empty_reply_retried = False
                for _ in range(max_tool_calls + 1):
                    reply = llm.chat(messages, tools)
                    tool_calls = reply.get("tool_calls") or []
                    content = reply.get("content") or ""
                    messages.append({
                        "role": "assistant",
                        "content": content,
                        **({"tool_calls": tool_calls} if tool_calls else {}),
                    })
                    if not tool_calls:
                        if content.strip():
                            final_text = content
                            break
                        # Occasionally the model answers with an empty message
                        # and no tool call (observed with deepseek-v4-flash).
                        # Nudge once instead of treating silence as the answer.
                        if empty_reply_retried:
                            final_text = "[eval harness: model returned an " \
                                "empty reply twice in a row]"
                            break
                        empty_reply_retried = True
                        messages.append({
                            "role": "user",
                            "content": "Your previous reply was empty. Give "
                                       "your final answer now as text.",
                        })
                        continue
                    if len(trace) + len(tool_calls) > max_tool_calls:
                        # budget exhausted: force a final answer without tools
                        messages.pop()
                        messages.append({
                            "role": "user",
                            "content": "Tool budget exhausted. Give your final "
                                       "answer now without calling tools.",
                        })
                        reply = llm.chat(messages, tools=None)
                        final_text = (reply.get("content") or "") + \
                            "\n[eval harness: tool budget exhausted]"
                        break
                    for call in tool_calls:
                        name = call["function"]["name"]
                        try:
                            arguments = json.loads(call["function"]["arguments"] or "{}")
                        except json.JSONDecodeError:
                            arguments = {}
                        try:
                            result = await session.call_tool(name, arguments)
                            text = _render_tool_result(result)
                            ok = not getattr(result, "isError", False)
                        except Exception as e:
                            text = "[tool call raised: %s]" % e
                            ok = False
                        trace.append(_trace_line(len(trace) + 1, name, arguments, ok, text))
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": text,
                        })
                else:
                    final_text = "[eval harness: loop limit reached without a final answer]"

                output = final_text + "\n\n---TOOL TRACE---\n" + \
                    ("\n".join(trace) if trace else "(no tool calls)")
                return {
                    "output": output,
                    "tokenUsage": {
                        "prompt": llm.usage["prompt"],
                        "completion": llm.usage["completion"],
                        "total": llm.usage["total"],
                    },
                }
    finally:
        llm.close()


def call_api(prompt, options, context):
    """promptfoo python provider entry point.

    promptfoo keeps one Python worker process alive across all cases in a
    run (its "persistent_wrapper"). Calling asyncio.run() repeatedly in that
    same process to spawn the MCP server subprocess is unreliable on Linux
    after a couple of iterations (observed: hangs or
    "ExceptionGroup: unhandled errors in a TaskGroup" from anyio's process
    spawn/child-watcher machinery once an event loop -> subprocess ->
    closed-event-loop cycle repeats a few times in one process). Each case
    is therefore run in its own throwaway subprocess so every case gets a
    fresh interpreter, event loop, and child watcher.
    """
    import subprocess
    config = (options or {}).get("config") or {}
    payload = json.dumps({"prompt": prompt, "config": config})
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker-run"],
            input=payload, capture_output=True, text=True, timeout=900,
        )
    except subprocess.TimeoutExpired:
        return {"error": "TimeoutExpired: case subprocess exceeded 900s"}
    if proc.returncode != 0:
        return {"error": "worker subprocess exited %d: %s" %
                 (proc.returncode, proc.stderr[-2000:])}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {"error": "could not parse worker output (%s): %s" %
                 (e, proc.stdout[-1000:])}


def _describe_exception(e):
    """Unpack (Base)ExceptionGroup nesting so the real cause survives being
    stringified, instead of just "unhandled errors in a TaskGroup"."""
    if hasattr(e, "exceptions"):
        parts = [_describe_exception(sub) for sub in e.exceptions]
        return "%s[%s]" % (type(e).__name__, "; ".join(parts))
    return "%s: %s" % (type(e).__name__, e)


def _worker_run():
    """Runs one case in its own fresh process; see call_api's docstring."""
    payload = json.loads(sys.stdin.read())
    try:
        result = asyncio.run(_run_case(payload["prompt"], payload["config"]))
    except Exception as e:
        result = {"error": _describe_exception(e)}
    print(json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker-run":
        _worker_run()
    else:
        question = sys.argv[1] if len(sys.argv) > 1 else \
            "Call bridge_status and report whether the bridge is connected."
        result = call_api(question, {"config": {}}, {})
        print(json.dumps(result.get("tokenUsage", {}), indent=2), file=sys.stderr)
        print(result.get("output") or ("ERROR: " + result.get("error", "?")))
