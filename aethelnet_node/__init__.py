# Aethelnet Node package
import os
import sys

_core_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "aethelnet-core"))
if os.path.isdir(_core_dir) and _core_dir not in sys.path:
    sys.path.insert(0, _core_dir)
