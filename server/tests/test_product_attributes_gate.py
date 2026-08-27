import re
from pathlib import Path
from types import SimpleNamespace

from services import product_attributes as product_attributes_service

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_GATE_MODULE = (_SERVER_ROOT / "services" / "product_attributes.py").resolve()
_SCAN_DIRS = ("services", "pipelines", "routers")
_SKU_ATTRIBUTES_RE = re.compile(r"\bsku\.attributes\b")


def test_prepare_write_keeps_allowed_keys_and_sku_identity() -> None:
    prepared = product_attributes_service.prepare_write(
        {"SKU": "A1", "Color": "Red", "HACK": "drop-me", "Size": ""},
        frozenset({"Color", "Size"}),
    )
    assert prepared == {"SKU": "A1", "Color": "Red", "Size": ""}


def test_apply_write_assigns_filtered_bag() -> None:
    sku = SimpleNamespace(attributes={})
    product_attributes_service.apply_write(
        sku,
        {"SKU": "A1", "Color": "Red", "HACK": "no"},
        frozenset({"Color"}),
    )
    assert sku.attributes == {"SKU": "A1", "Color": "Red"}


def test_services_pipelines_routers_do_not_touch_sku_attributes() -> None:
    """Bypassing product_attributes is a bug — keep the JSONB column behind the gate."""
    violations: list[str] = []
    for folder in _SCAN_DIRS:
        for path in (_SERVER_ROOT / folder).rglob("*.py"):
            if path.resolve() == _GATE_MODULE:
                continue
            text = path.read_text(encoding="utf-8")
            for index, line in enumerate(text.splitlines(), start=1):
                if _SKU_ATTRIBUTES_RE.search(line):
                    rel = path.relative_to(_SERVER_ROOT)
                    violations.append(f"{rel}:{index}: {line.strip()}")
    assert violations == []
