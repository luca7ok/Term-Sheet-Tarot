import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "tarot",
        "tarot.schemas",
        "tarot.ingest",
        "tarot.retrieval",
        "tarot.ontology",
        "tarot.mcp_server",
    ],
)
def test_package_imports(module):
    importlib.import_module(module)
