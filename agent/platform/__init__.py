"""
agent/platform — operating-system specific code.

`system` is the module for the current OS. Other modules use it like:

    from agent.platform import system
    system.notify("Commit", "Hello")

macOS is supported now; Windows (windows.py) comes in Phase 4.
"""

import sys

if sys.platform == "darwin":
    from agent.platform import macos as system
else:
    raise RuntimeError("Commit currently supports macOS only. Windows support arrives in Phase 4.")

__all__ = ["system"]
