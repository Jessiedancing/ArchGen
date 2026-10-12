"""GraphIR → 原生 draw.io（mxGraphModel）。节点可单独选中/改字/改色，连线跟随。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from graph_ir import sanitize_xml

try:
    from design_tokens import shape_colors
except Exception:  # noqa: BLE001
    def shape_colors() -> dict[str, str]:
        return {"fill": "#e7effe", "stroke": "#6ea8dc", "text": "#17427e"}


_ID_SAFE = re.compile(r"[^\w.\-]+")


def _cell_id(raw: str, used: set[str]) -> str:
    base = _ID_SAFE.sub("_", str(raw or "n")) or "n"
    if base[0].isdigit():
        base = "n" + base
    cand = base[:64]
    i = 2
    while cand in used:
        cand = f"{base[:56]}_{i}"
        i += 1
    used.add(cand)
    return cand


def _shape_style(node: dict[str, Any], colors: dict[str, str]) -> str:
    fill = node.get("fill") or colors.get("fill") or "#e7effe"
    stroke = node.get("stroke") or colors.get("stroke") or "#6ea8dc"
    font = colors.get("text") or "#17427e"
    kind = str(node.get("shape") or "round")
    if kind == "ellipse":
        shape = "ellipse;"
    elif kind == "bar":
        shape = "rounded=0;"
    else:
        shape = "rounded=1;arcSize=12;"
    return (
        f"{shape}whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
        f"fillColor={fill};strokeColor={stroke};fontColor={font};"
        f"fontSize={int(round(float(node.get('font_px') or 12)))};"
        "fontFamily=Helvetica;"
    )


def _edge_style(edge: dict[str, Any]) -> str:
    dashed = "dashed=1;dashPattern=8 8;" if edge.get("dashed") else ""
    return f"endArrow=block;html=1;strokeWidth=1.4;{dashed}edgeStyle=orthogonalEdgeStyle;"


def ir_to_drawio_xml(ir: dict[str, Any]) -> str:
    colors = shape_colors()
    title = sanitize_xml(ir.get("title") or "ArchGen")
    size = ir.get("size") or {}
    page_w = max(int(size.get("w") or 1180), 800)
    page_h = max(int(size.get("h") or 700), 600)
    used: set[str] = {"0", "1"}
    id_map: dict[str, str] = {}
    cells: list[str] = [
        '<mxCell id="0"/>',
        '<mxCell id="1" parent="0"/>',
    ]

    for node in ir.get("nodes") or []:
        nid = _cell_id(str(node.get("id") or "n"), used)
        id_map[str(node.get("id"))] = nid
        value = sanitize_xml(str(node.get("text") or "").replace("\n", "&#10;"))
        style = _shape_style(node, colors)
        x = float(node.get("x") or 0)
        y = float(node.get("y") or 0)
        w = max(float(node.get("w") or 40), 8)
        h = max(float(node.get("h") or 20), 8)
        cells.append(
            f'<mxCell id="{nid}" value="{value}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/>'
            "</mxCell>"
        )

    seen_edges: set[tuple[str, str]] = set()
    for i, edge in enumerate(ir.get("edges") or []):
        src = id_map.get(str(edge.get("from")))
        dst = id_map.get(str(edge.get("to")))
        if not src or not dst or src == dst:
            continue
        key = (src, dst)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        eid = _cell_id(f"e{i}", used)
        label = sanitize_xml(str(edge.get("label") or ""))
        cells.append(
            f'<mxCell id="{eid}" value="{label}" style="{_edge_style(edge)}" '
            f'edge="1" parent="1" source="{src}" target="{dst}">'
            '<mxGeometry relative="1" as="geometry"/>'
            "</mxCell>"
        )

    inner = "\n        ".join(cells)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<mxfile host="ArchGen" agent="ArchGen" version="0.4">\n'
        f'  <diagram id="archgen" name="{title}">\n'
        f'    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" '
        f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{page_w}" pageHeight="{page_h}" math="0" shadow="0">\n'
        f"      <root>\n        {inner}\n      </root>\n"
        "    </mxGraphModel>\n"
        "  </diagram>\n"
        "</mxfile>\n"
    )


def write_drawio(ir: dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.write_text(ir_to_drawio_xml(ir), encoding="utf-8")
    return path
