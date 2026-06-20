import logging
import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aethelnet_node.database import get_node_text

logger = logging.getLogger("Aethelnet.Node.Runtime")

router = APIRouter()

class OmniDecodeRequest(BaseModel):
    source_node: str
    format: str  # 'TEXT', 'UI', 'IMAGE', 'AUDIO'
    prompt: str = ""

class NaasRequest(BaseModel):
    inputs: Optional[Dict[str, Any]] = None

@router.post("/decoder/omni")
async def omni_decode(data: OmniDecodeRequest):
    """
    The Omni Decoder. Translates a node's topological context into an arbitrary format.
    """
    node_text = get_node_text(data.source_node)
    if not node_text:
        raise HTTPException(status_code=404, detail="Source node not found in latent space.")
    
    if data.format == "TEXT":
        res = f"Decoded TEXT output for {data.source_node}: {node_text}"
        return {"status": "success", "format": "TEXT", "content": res}
        
    elif data.format == "UI":
        res = f"<div class='p-4 bg-gray-800 text-white rounded font-mono shadow-lg border border-gray-600'><h3>Node: {data.source_node}</h3><p>{node_text}</p></div>"
        return {"status": "success", "format": "UI", "content": res}
        
    elif data.format == "IMAGE":
        return {
            "status": "success", 
            "format": "IMAGE", 
            "content": f"https://image.pollinations.ai/prompt/abstract%20graph%20node%20{data.source_node}?width=512&height=512&nologo=true"
        }
        
    elif data.format == "AUDIO":
        return {"status": "success", "format": "AUDIO", "content": "[AUDIO SYNTHESIS PENDING]"}
        
    raise HTTPException(status_code=400, detail="Unknown format requested.")

@router.post("/naas/{node_id}")
@router.get("/naas/{node_id}")
async def naas_endpoint(node_id: str, request: Request, req_data: Optional[NaasRequest] = None):
    # 1. Resolve inputs
    inputs = {}
    if request.method == "POST":
        if req_data and req_data.inputs:
            inputs = req_data.inputs
        else:
            try:
                body = await request.json()
                inputs = body.get("inputs", {})
            except Exception:
                pass
    # Merge query parameters
    query_params = dict(request.query_params)
    inputs.update(query_params)
    
    # 2. Get the node text content
    node_text = get_node_text(node_id)
            
    if not node_text:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found or has no content.")
        
    # Remove prefix if present
    content = node_text
    is_lua = False
    is_python = False
    is_prompt = False
    
    if content.startswith("APP:Lua"):
        content = content[len("APP:Lua"):].strip()
        is_lua = True
    elif content.startswith("APP:Python"):
        content = content[len("APP:Python"):].strip()
        is_python = True
    elif "lua" in node_id.lower() or "lua" in node_text.lower()[:30]:
        is_lua = True
    elif "python" in node_id.lower() or "python" in node_text.lower()[:30]:
        is_python = True
    elif "{" in content and "}" in content:
        is_prompt = True

    # 3. Execution logic
    if is_lua:
        try:
            from lupa import LuaRuntime
            lua = LuaRuntime(unpack_returned_tuples=True)
            
            lua_globals = lua.globals()
            lua_inputs = lua.table()
            for k, v in inputs.items():
                lua_inputs[k] = v
            lua_globals.inputs = lua_inputs
            
            result = lua.execute(content)
            return {"status": "success", "engine": "lua", "result": str(result) if result is not None else "nil"}
        except Exception as e:
            return {"status": "error", "engine": "lua", "message": str(e)}
            
    elif is_python:
        try:
            local_vars = {"inputs": inputs, "result": None}
            import io
            import sys
            old_stdout = sys.stdout
            redirected_output = sys.stdout = io.StringIO()
            
            exec(content, {}, local_vars)
            
            sys.stdout = old_stdout
            stdout_val = redirected_output.getvalue()
            
            res_val = local_vars.get("result")
            if res_val is None and stdout_val:
                res_val = stdout_val.strip()
                
            return {"status": "success", "engine": "python", "result": res_val}
        except Exception as e:
            return {"status": "error", "engine": "python", "message": str(e)}
            
    elif is_prompt:
        formatted_prompt = content
        for k, v in inputs.items():
            placeholder = "{" + k + "}"
            if placeholder in formatted_prompt:
                formatted_prompt = formatted_prompt.replace(placeholder, str(v))
                
        return {"status": "success", "engine": "ai", "result": f"[Simulated AI Response for: {formatted_prompt}]"}
            
    else:
        return {"status": "success", "engine": "static", "result": content}
