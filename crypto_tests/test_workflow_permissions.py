"""Validate local reusable-workflow permission ceilings before a manual run."""
from pathlib import Path
from copy import deepcopy

import pytest

yaml = pytest.importorskip("yaml", reason="host-only workflow validation uses the existing PyYAML dependency")
WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
LEVEL = {"none": 0, "read": 1, "write": 2}


def ceiling_errors(caller_permissions, callee):
    errors = []
    for name, job in callee["jobs"].items():
        requested = job.get("permissions", callee.get("permissions", caller_permissions))
        assert isinstance(requested, dict) and isinstance(caller_permissions, dict)
        for scope, level in requested.items():
            if LEVEL[level] > LEVEL[caller_permissions.get(scope, "none")]:
                errors.append((name, scope, level))
    return errors


def test_local_reusable_workflow_permissions_do_not_exceed_callers():
    for path in WORKFLOWS.glob("*.yml"):
        caller = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in caller.get("jobs", {}).items():
            uses = job.get("uses", "")
            if not uses.startswith("./.github/workflows/"):
                continue
            callee = yaml.safe_load((WORKFLOWS / Path(uses).name).read_text(encoding="utf-8"))
            permissions = job.get("permissions", caller.get("permissions", {}))
            assert not ceiling_errors(permissions, callee), f"{path.name}/{name} exceeds caller permissions"


def test_original_sync_startup_failure_is_detected():
    caller = yaml.safe_load((WORKFLOWS / "crypto-upstream-sync.yml").read_text(encoding="utf-8"))
    callee = yaml.safe_load((WORKFLOWS / "crypto-compat.yml").read_text(encoding="utf-8"))
    permissions = deepcopy(caller["jobs"]["compatibility"]["permissions"])
    permissions.pop("statuses", None)
    assert ("required-status", "statuses", "write") in ceiling_errors(permissions, callee)
