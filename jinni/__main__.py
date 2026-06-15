"""Run the jinni as a process: `python -m jinni <socket-path>`.

The daemon spawns this as its parented child (ADR-0037). The jinni loads the device adapter, does
its own in-process lifecycle (startup control scripts, background tasks), and serves the contract on
the socket until killed.
"""
import asyncio
import sys

from . import service

if __name__ == "__main__":
    asyncio.run(service.run(sys.argv[1]))
