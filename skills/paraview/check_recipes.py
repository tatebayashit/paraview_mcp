"""Run every ```python block of SKILL.md, in order, through a running bridge.

Usage: python check_recipes.py /path/to/case.foam [host:port]   (default 127.0.0.1:9911)
Needs an OpenFOAM case with cell arrays U and p and a patch named movingWall (any
cavity tutorial). Re-run after a ParaView upgrade; last verified on 6.1.1.
"""
import json
import pathlib
import re
import socket
import sys

case = sys.argv[1]
host, _, port = (sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1:9911").partition(":")
text = pathlib.Path(__file__).with_name("SKILL.md").read_text(encoding="utf-8")
blocks = re.findall(r"```python\n(.*?)```", text, re.S)
assert blocks, "no python blocks found in SKILL.md"


def call(code):
    req = {"v": 1, "id": "check", "op": "exec", "code": code, "render": False}
    with socket.create_connection((host, int(port)), timeout=600) as s:
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("bridge closed the connection")
            buf += chunk
    return json.loads(buf.split(b"\n")[0])


for i, code in enumerate(blocks, 1):
    code = code.replace('"/path/to/case/case.foam"', json.dumps(case))
    resp = call(code)
    assert resp["status"] == "ok", "block %d failed:\n%s\n%s" % (
        i, code, json.dumps(resp.get("error"), indent=1))
    print("block %d ok: %s" % (i, str(resp.get("value") or "")[:160]))
print("all %d blocks ok" % len(blocks))
