"""Worker entrypoint: discovers workflows and runs the worker."""

import asyncio

import mistralai.workflows as workflows


async def main() -> None:
    discovered = workflows.discover_all_workflows_in_package("workflows")
    await workflows.run_worker(discovered)


if __name__ == "__main__":
    asyncio.run(main())
