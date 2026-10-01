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

from aethelnet_node.state import graph_instance, node_metrics, REALITY_ANCHORS
import urllib.parse

@router.post("/decoder/omni")
async def omni_decode(data: OmniDecodeRequest):
    """
    The Omni Decoder. Translates a node's continuous topological context into an arbitrary format.
    """
    safe_id = graph_instance._safe_id(data.source_node)
    node_text = get_node_text(data.source_node)
    
    if not node_text and safe_id in node_metrics:
        node_text = node_metrics[safe_id].get("text_content", "")
        
    if not node_text and data.source_node in REALITY_ANCHORS:
        node_text = f"{data.source_node}: {REALITY_ANCHORS[data.source_node].get('desc', '')}"
        
    if not node_text and (data.source_node in graph_instance.nodes or safe_id in graph_instance.nodes):
        node_text = f"Continuous latent concept node: {data.source_node}"
        
    if not node_text:
        raise HTTPException(status_code=404, detail=f"Source node '{data.source_node}' not found in neural lattice.")
    
    fmt = data.format.upper().strip()
    if fmt == "TEXT":
        if data.prompt:
            res = (
                f"### [DECODED PERSPECTIVE: {data.source_node}]\n"
                f"**Instruction:** {data.prompt}\n\n"
                f"**Latent Substrate:** {node_text}\n\n"
                f"**Topological Synthesis:** Concept `{data.source_node}` anchors continuous state transformations, "
                f"resonating through synaptic bridges with active feedback damping."
            )
        else:
            res = (
                f"### [DECODED TOPOLOGY: {data.source_node}]\n\n"
                f"{node_text}\n\n"
                f"---\n"
                f"*Identity:* `{data.source_node}` | *Lattice State:* Synchronized Continuous ODE"
            )
        return {"status": "success", "format": "TEXT", "content": res}
        
    elif fmt == "UI":
        res = (
            f"<div style='background: rgba(3,7,18,0.95); border: 1px solid #00f3ff; padding: 16px; border-radius: 4px; font-family: monospace;'>"
            f"<div style='color: #00f3ff; font-weight: bold; font-size: 13px; margin-bottom: 8px;'>[ NODE: {data.source_node} ]</div>"
            f"<div style='color: rgba(255,255,255,0.85); font-size: 11px; margin-bottom: 12px; line-height: 1.5;'>{node_text}</div>"
            f"<div style='display: flex; gap: 8px; font-size: 10px;'>"
            f"<span style='background: rgba(0,243,255,0.15); color: #00f3ff; padding: 2px 6px; border: 1px solid rgba(0,243,255,0.4);'>ODE ACTIVE</span>"
            f"<span style='background: rgba(16,185,129,0.15); color: #10b981; padding: 2px 6px; border: 1px solid rgba(16,185,129,0.4);'>GROUNDED</span>"
            f"</div></div>"
        )
        return {"status": "success", "format": "UI", "content": res}
        
    elif fmt == "IMAGE":
        img_prompt = data.prompt if data.prompt else f"cyberpunk neural concept visualization of {data.source_node}, neon glowing nodes and synapses, hyperdetailed dark aesthetic"
        encoded_prompt = urllib.parse.quote(img_prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=512&height=512&nologo=true"
        return {
            "status": "success", 
            "format": "IMAGE", 
            "content": image_url
        }
        
    elif fmt == "AUDIO":
        freq = (abs(hash(data.source_node)) % 300) + 220
        res = f"Harmonic resonance active at {freq}Hz (Carrier: 432Hz cognitive fundamental, modulation index: 1.618)."
        return {"status": "success", "format": "AUDIO", "content": res}
        
    raise HTTPException(status_code=400, detail=f"Unknown format requested: {data.format}")

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
