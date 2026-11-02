import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"


def test_published_openapi_document_is_up_to_date():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    published = module.OPENAPI_PATH.read_text("utf-8")

    assert published == module.render_openapi(), "run `make docs-openapi` and commit the result"
