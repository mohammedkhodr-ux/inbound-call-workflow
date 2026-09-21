"""Worker entrypoint for the Digital Dubai inbound call workflow.

Discovers the workflow definitions and starts the Mistral Workflows worker.
Run with:  make start-worker   (or)   python -m entrypoints.worker
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    import mistralai.workflows as workflows

    discovered = workflows.discover_all_workflows_in_package("workflows")
    if not discovered:
        raise RuntimeError("No workflows discovered in src/workflows")
    await workflows.run_worker(discovered)


if __name__ == "__main__":
    asyncio.run(main())
