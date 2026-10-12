"""
Aethelnet Visual Provenance & Dynamic Styling.

Maps any agent_id (human or AI) deterministically to a vibrant, distinct color signature
using SHA-256 hashing. Also checks agents.json for custom color overrides.
Eliminates hardcoded model/user styling.
"""

import colorsys
import hashlib
from typing import Dict, Any, Optional
from aethelnet_node.agents import load_agents


def agent_id_to_color(agent_id: str, custom_override: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns deterministic visual styling for an agent identity.
    Output format:
    {
        "agent_id": str,
        "hex": "#3b82f6",
        "hsl": "hsl(217, 75%, 60%)",
        "rgb": [59, 130, 246],
        "hue": 217,
        "is_custom": bool
    }
    """
    agent_id = str(agent_id or "unknown").strip().lower()

    # 1. Check custom override from agents.json if available
    if not custom_override:
        agents = load_agents()
        agent_data = agents.get(agent_id, {})
        custom_override = agent_data.get("color")

    if custom_override and custom_override.startswith("#") and len(custom_override) == 7:
        try:
            r = int(custom_override[1:3], 16)
            g = int(custom_override[3:5], 16)
            b = int(custom_override[5:7], 16)
            h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
            return {
                "agent_id": agent_id,
                "hex": custom_override.lower(),
                "hsl": f"hsl({int(h * 360)}, {int(s * 100)}%, {int(l * 100)}%)",
                "rgb": [r, g, b],
                "hue": int(h * 360),
                "is_custom": True
            }
        except Exception:
            pass

    # 2. Deterministic Golden Ratio / SHA-256 Hashing for vibrant spread
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()
    hue = (int(digest[:8], 16) % 360) / 360.0
    saturation = 0.75
    lightness = 0.58

    r_f, g_f, b_f = colorsys.hls_to_rgb(hue, lightness, saturation)
    r = int(r_f * 255)
    g = int(g_f * 255)
    b = int(b_f * 255)
    hex_color = f"#{r:02x}{g:02x}{b:02x}"
    hsl_str = f"hsl({int(hue * 360)}, {int(saturation * 100)}%, {int(lightness * 100)}%)"

    return {
        "agent_id": agent_id,
        "hex": hex_color,
        "hsl": hsl_str,
        "rgb": [r, g, b],
        "hue": int(hue * 360),
        "is_custom": False
    }
