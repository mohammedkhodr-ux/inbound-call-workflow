"""Regression tests for the Temporal determinism sandbox.

The workflow module is re-imported inside the sandbox with only
``mistralai.workflows`` passed through; a module-level third-party import
(httpx, smtplib, email.message) makes every execution fail at startup with
``RestrictedWorkflowAccessError``. These tests reproduce that import exactly,
so the regression cannot come back unnoticed — they need no Temporal server.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _snapshot_modules() -> dict:
    """Snapshot user modules so the test can restore them afterwards."""
    return {m: mod for m, mod in sys.modules.items() if m.startswith(("integrations", "workflows"))}


def _purge_user_modules() -> None:
    """Drop user modules so the sandboxed import cannot reuse cached ones."""
    for name in [m for m in sys.modules if m.startswith(("integrations", "workflows"))]:
        del sys.modules[name]


def _restore_modules(snapshot: dict) -> None:
    """Restore the exact module objects captured before the sandboxed import.

    Without this, later tests re-import user modules and get *fresh* module
    objects whose monkeypatched attributes no longer line up with the classes
    already imported elsewhere in the session.
    """
    _purge_user_modules()
    sys.modules.update(snapshot)


def test_workflow_module_imports_under_sandbox_restrictions() -> None:
    """The worker sandbox must be able to import the workflow module.

    This mirrors what ``SandboxedWorkflowRunner`` does when loading a workflow:
    re-import the module under ``get_sandbox_restrictions()``. A top-level
    ``import httpx`` in anything the workflow module touches (including the
    integration helpers) fails here first.
    """
    pytest.importorskip("temporalio")
    from mistralai.workflows.core.sandbox import get_sandbox_restrictions
    from temporalio.worker.workflow_sandbox import _importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    snapshot = _snapshot_modules()
    try:
        _purge_user_modules()
        importer = _importer.Importer(get_sandbox_restrictions(), RestrictionContext())
        with importer.applied():
            try:
                import workflows.inbound_call  # noqa: F401

                loaded = True
            except Exception:
                loaded = False
            finally:
                _purge_user_modules()
    finally:
        _restore_modules(snapshot)
    assert loaded, "workflow module must import under sandbox restrictions"


def test_no_third_party_top_level_imports() -> None:
    """Static guard: keep the workflow and integration modules sandbox-safe.

    ``mistralai``, ``pydantic``, ``structlog`` and plain stdlib are passed
    through by the SDK sandbox; anything else (httpx, smtplib, email) must be
    imported lazily inside activities under
    ``workflow.unsafe.imports_passed_through()``.
    """
    allowed = {
        "mistralai",
        "pydantic",
        "structlog",
        "temporalio",
        "integrations",
        "workflows",
        "entrypoints",
        "typing",
        "asyncio",
        "pathlib",
        "functools",
        "os",
        "sys",
        "base64",
        "datetime",
        "__future__",
    }
    violations: list[str] = []
    for module in sorted(Path(SRC).rglob("*.py")):
        for line in module.read_text().splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if line.startswith((" ", "\t")):
                continue  # function-local / TYPE_CHECKING imports are fine
            root = stripped.split()[1].split(".")[0].rstrip(",")
            if root not in allowed:
                violations.append(f"{module.relative_to(SRC)}: {stripped}")
    assert not violations, "Sandbox-unsafe top-level imports:\n" + "\n".join(violations)
