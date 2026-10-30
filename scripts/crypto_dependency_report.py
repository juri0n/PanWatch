"""Actual installed metadata inventory, including development tooling. Not a license opinion."""
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
import platform
import sys


def inventory():
    packages = []
    for distribution in metadata.distributions():
        info = distribution.metadata
        packages.append({"name": info["Name"], "version": distribution.version,
                         "requires_python": info.get("Requires-Python"),
                         "license_expression": info.get("License-Expression"),
                         "license_field": info.get("License"),
                         "license_classifiers": [c for c in info.get_all("Classifier", []) if c.startswith("License")],
                         "requires_dist": distribution.requires or []})
    return {"at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
            "platform": platform.platform(), "scope": "isolated crypto/test environment; not full PanWatch",
            "packages": sorted(packages, key=lambda item: item["name"].lower())}


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as stream:
        json.dump(inventory(), stream, ensure_ascii=False, indent=2)
