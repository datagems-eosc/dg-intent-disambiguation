"""Write the service's OpenAPI document to docs/docs/content/openapi.json.

The documentation site renders it on its OpenAPI page. Run `make docs-openapi` after
changing the API; tests/test_openapi_doc.py fails while the file is out of date.
"""

import json
from dataclasses import replace
from pathlib import Path

from intent_disambiguation.config import Settings
from intent_disambiguation.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "docs" / "docs" / "content" / "openapi.json"


def render_openapi() -> str:
    # No path prefix: the documented paths are relative to the service's base URL
    settings = replace(Settings.from_env(), base_url="", enable_auth=False)
    spec = create_app(settings=settings).openapi()
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(render_openapi(), "utf-8")
    print(f"Wrote {OPENAPI_PATH}")
