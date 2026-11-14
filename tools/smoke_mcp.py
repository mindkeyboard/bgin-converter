"""Exercise the packaged stdio server with no Python import dependencies."""

import json
from pathlib import Path
import subprocess
import queue
import threading


def smoke_mcp(executable, fixture, directory, env):
    directory = Path(directory)
    output = directory / "mcp-export.bgin"
    source = {"path": str(fixture)}
    requests = [
        {"id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "BGIN native smoke", "version": "1"}}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "resources/read", "params": {"uri": "bgin://skill"}},
        {"id": 3, "method": "tools/call", "params": {"name": "bgin_editor", "arguments": {}}},
        {"id": 4, "method": "tools/call", "params": {"name": "bgin_read", "arguments": {"source": source}}},
        {"id": 5, "method": "tools/call", "params": {"name": "bgin_edit", "arguments": {
            "source": source, "operations": [{"op": "replace", "path": "/screens/0/children/0/properties/TestString", "value": "Compiled MCP"}]}}},
        {"id": 6, "method": "tools/call", "params": {"name": "bgin_export", "arguments": {"source": source, "destination": str(output)}}},
        {"id": 7, "method": "tools/call", "params": {"name": "bgin_read", "arguments": {"source": {"path": str(output)}}}},
    ]
    replies = {}
    with (directory / "mcp-stderr.log").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [*(executable if isinstance(executable, list) else [str(executable)]), "--mcp", "--mode", "standalone", "--config", str(directory / "mcp-settings.json")],
            encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            cwd=directory, env=env,
        )
        messages = queue.Queue()

        def read():
            for line in process.stdout:
                messages.put(json.loads(line))
            messages.put(None)

        threading.Thread(target=read, daemon=True).start()
        try:
            for item in requests:
                if item.get("id") == 6:
                    edit_result = replies[5]["result"]
                    edited = edit_result.get("structuredContent") or json.loads(next(
                        block["text"] for block in edit_result["content"] if block["type"] == "text"))
                    item["params"]["arguments"]["source"] = {"document": edited["document"]}
                process.stdin.write(json.dumps({"jsonrpc": "2.0", **item}) + "\n")
                process.stdin.flush()
                if "id" not in item:
                    continue
                while True:
                    response = messages.get(timeout=90)
                    if response is None:
                        raise ValueError("MCP closed before replying; inspect mcp-stderr.log")
                    if response.get("id") == item["id"]:
                        replies[item["id"]] = response
                        break
            process.stdin.close()
            if process.wait(timeout=30):
                raise ValueError("Packaged MCP failed; inspect mcp-stderr.log")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
    for reply in replies.values():
        if "error" in reply or reply.get("result", {}).get("isError"):
            raise ValueError(f"MCP request failed: {reply}")
    def result(identifier):
        value = replies[identifier]["result"]
        return value.get("structuredContent") or json.loads(next(item["text"] for item in value["content"] if item["type"] == "text"))
    if "Read bgin://skill" not in replies[1]["result"]["instructions"]:
        raise ValueError("MCP instructions are missing")
    if not replies[2]["result"]["contents"][0]["text"]:
        raise ValueError("Packaged editing skill is missing")
    if result(3)["mode"] != "standalone":
        raise ValueError("MCP mode is incorrect")
    edited = result(5)["document"]
    if edited["screens"][0]["children"][0]["properties"]["TestString"] != "Compiled MCP":
        raise ValueError("MCP edit did not change the document")
    if (output.read_bytes() == Path(fixture).read_bytes()
            or not result(6)["independentBinaryCheck"]
            or result(7)["document"]["screens"][0]["children"][0]["properties"]["TestString"] != "Compiled MCP"):
        raise ValueError("MCP export did not pass the independent binary check")
    print("Packaged MCP: initialize, skill, read, edit and independent export passed without Python on PATH")
