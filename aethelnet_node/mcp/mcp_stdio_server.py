#!/usr/bin/env python3
import sys
import json
import urllib.request
import traceback

API_URL = "http://127.0.0.1:8000/api/lgnn"

def send_response(id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": id}
    if error:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()

def handle_request(req):
    method = req.get("method")
    params = req.get("params", {})
    req_id = req.get("id")
    
    try:
        if method == "initialize":
            send_response(req_id, result={
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lgnn_mcp", "version": "1.0.0"}
            })
            
        elif method == "notifications/initialized":
            pass # No response needed for notifications
            
        elif method == "tools/list":
            url = f"{API_URL}/mcp/tools"
            r = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(r, timeout=10) as res:
                data = json.loads(res.read().decode('utf-8'))
                send_response(req_id, result={"tools": data.get("tools", [])})
                
        elif method == "tools/call":
            url = f"{API_URL}/mcp/tools/call"
            name = params.get("name")
            args = params.get("arguments", {})
            payload = json.dumps({"name": name, "arguments": args}).encode("utf-8")
            
            r = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(r, timeout=60) as res:
                data = json.loads(res.read().decode('utf-8'))
                # Backend returns {"content": [...], "isError": bool}
                send_response(req_id, result={
                    "content": data.get("content", [{"type": "text", "text": "Empty response"}]),
                    "isError": data.get("isError", False)
                })
        else:
            send_response(req_id, error={"code": -32601, "message": f"Method {method} not found"})
            
    except Exception as e:
        send_response(req_id, error={"code": -32603, "message": f"Internal error: {str(e)}"})

def main():
    for line in sys.stdin:
        if not line.strip(): continue
        try:
            req = json.loads(line)
            handle_request(req)
        except Exception as e:
            # Parse error
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", 
                "error": {"code": -32700, "message": "Parse error"}
            }) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
