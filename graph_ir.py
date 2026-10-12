"""GraphIR 中间层（ADR 011 / T00）：绝对坐标，供 drawio / pptx 共用。

两条 producer：
- architecture：分层 JSON → 绝对坐标，复用 `_chip_columns` 规则
- Mermaid：截图时从 SVG / DOM 抽 bbox（与 PNG 同一坐标系，相对 #capture）
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

# 截图页里相对 #capture 抽节点/边。Mermaid 各图种的 SVG 结构不统一，
# 用 bbox + 最近邻配对，不依赖特定 class 命名。
EXTRACT_IR_JS = r"""
() => {
  const cap = document.querySelector("#capture");
  if (!cap) return null;
  const root = cap.getBoundingClientRect();
  const title = ((cap.querySelector("h1") || {}).textContent || "").trim();

  function hexColor(css) {
    if (!css || css === "none" || css === "transparent") return "";
    const m = css.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!m) return css.startsWith("#") ? css : "";
    const n = (x) => ("0" + Number(x).toString(16)).slice(-2);
    return "#" + n(m[1]) + n(m[2]) + n(m[3]);
  }
  function boxOf(el) {
    const r = el.getBoundingClientRect();
    return {
      x: Math.round((r.left - root.left) * 10) / 10,
      y: Math.round((r.top - root.top) * 10) / 10,
      w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10,
    };
  }

  const nodes = [];
  const chips = cap.querySelectorAll(".chip, .layer-title, .group h3");
  if (chips.length) {
    cap.querySelectorAll(".layer").forEach((layer, li) => {
      const lname = ((layer.querySelector(".layer-title") || {}).textContent || ("L" + li)).trim();
      const titleEl = layer.querySelector(".layer-title");
      if (titleEl) {
        const b = boxOf(titleEl);
        const cs = getComputedStyle(titleEl);
        nodes.push({
          id: "L" + li + "-title", x: b.x, y: b.y, w: b.w, h: b.h,
          text: lname, fill: hexColor(cs.backgroundColor) || "#e9f3fe",
          stroke: hexColor(getComputedStyle(layer).borderColor) || "#6ea8dc",
          shape: "bar", font_px: 15, group: lname,
        });
      }
      layer.querySelectorAll(".chip").forEach((chip, ci) => {
        const b = boxOf(chip);
        const cs = getComputedStyle(chip);
        const text = (chip.innerText || "").replace(/\s+/g, " ").trim();
        nodes.push({
          id: "L" + li + "-C" + ci, x: b.x, y: b.y, w: b.w, h: b.h,
          text: text, fill: hexColor(cs.backgroundColor) || "#ffffff",
          stroke: hexColor(cs.borderColor) || "#6ea8dc",
          shape: "round", font_px: 12.5, group: lname,
        });
      });
    });
    const edges = [];
    const titles = nodes.filter((n) => n.shape === "bar");
    for (let i = 0; i < titles.length - 1; i++) {
      edges.push({ from: titles[i].id, to: titles[i + 1].id, label: "", dashed: titles[i + 1].id.includes("ext") ? true : i === titles.length - 2 && /外部/.test(titles[i + 1].text), points: [] });
    }
    return { title: title, size: { w: Math.round(root.width), h: Math.round(root.height) }, nodes: nodes, edges: edges, source: "dom" };
  }

  const svg = cap.querySelector("svg");
  if (!svg) return { title: title, size: { w: Math.round(root.width), h: Math.round(root.height) }, nodes: [], edges: [], source: "empty" };

  const skip = /edgeLabel|edgePath|marker|cluster-label|title|subtitle/i;
  svg.querySelectorAll("g.node, g.actor, g.stateGroup > g, g[id^='entity']").forEach((g, i) => {
    if (skip.test(g.getAttribute("class") || "") || skip.test(g.getAttribute("id") || "")) return;
    const shapeEl = g.querySelector("rect, circle, ellipse, polygon, path.basic");
    const target = shapeEl || g;
    const b = boxOf(target);
    if (b.w < 4 || b.h < 4 || b.w > root.width * 1.2) return;
    const label = g.querySelector(".nodeLabel, .label, foreignObject, .actor, .entityLabel");
    const text = ((label && label.innerText) || g.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) return;
    const cs = getComputedStyle(shapeEl || g);
    const id = (g.getAttribute("id") || ("n" + i)).replace(/[^\w\-.:]/g, "_");
    nodes.push({
      id: id, x: b.x, y: b.y, w: b.w, h: b.h, text: text.slice(0, 200),
      fill: hexColor(cs.fill) || hexColor(cs.backgroundColor) || "#e7effe",
      stroke: hexColor(cs.stroke) || "#6ea8dc",
      shape: (shapeEl && shapeEl.tagName.toLowerCase() === "circle") ? "ellipse" : "round",
      font_px: 14, group: "",
    });
  });

  function svgToCap(x, y) {
    const pt = svg.createSVGPoint();
    pt.x = x; pt.y = y;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: x, y: y };
    const sp = pt.matrixTransform(ctm);
    return { x: sp.x - root.left, y: sp.y - root.top };
  }
  function nearest(x, y) {
    let best = null, bestD = 1e12;
    nodes.forEach((n) => {
      const cx = n.x + n.w / 2, cy = n.y + n.h / 2;
      const d = (cx - x) * (cx - x) + (cy - y) * (cy - y);
      if (d < bestD) { bestD = d; best = n; }
    });
    return best;
  }

  const edges = [];
  svg.querySelectorAll("g.edgePath path, .edgePaths path, path[class*='flowchart-link']").forEach((path, i) => {
    try {
      const len = path.getTotalLength();
      if (!len) return;
      const a = path.getPointAtLength(0);
      const b = path.getPointAtLength(len);
      const p0 = svgToCap(a.x, a.y);
      const p1 = svgToCap(b.x, b.y);
      const src = nearest(p0.x, p0.y);
      const dst = nearest(p1.x, p1.y);
      if (!src || !dst || src.id === dst.id) return;
      const dash = (path.getAttribute("stroke-dasharray") || "").length > 0;
      edges.push({ from: src.id, to: dst.id, label: "", dashed: dash, points: [] });
    } catch (e) { /* 个别 path 无 getTotalLength */ }
  });

  return { title: title, size: { w: Math.round(root.width), h: Math.round(root.height) }, nodes: nodes, edges: edges, source: "svg" };
}
"""


def new_ir(title: str = "", w: float = 0, h: float = 0) -> dict[str, Any]:
    return {"title": title, "size": {"w": w, "h": h}, "nodes": [], "edges": []}


def write_ir(path: Path, ir: dict[str, Any]) -> Path:
    path.write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_ir(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "nodes" not in data:
        raise ValueError(f"不是 GraphIR：{path}")
    return data


def layered_json_to_ir(data: dict[str, Any]) -> dict[str, Any]:
    """Producer A：分层 JSON → 绝对坐标，复用 `_chip_columns`（T00）。"""
    from render_diagram import (  # noqa: WPS433 — 避免循环导入
        EXTERNAL_THEME,
        LAYER_THEMES,
        _chip_columns,
        _normalize_items,
        _page_layout,
    )

    layout = _page_layout()
    page_w = int(layout["width"])
    pad = int(layout["padding"])
    gap = layout["group_gap"]
    chip_gap = layout["chip_gap"]
    chip_h = 32.0
    title = str(data.get("title") or "技术架构图")
    subtitle = str(data.get("subtitle") or "")
    layers = data.get("layers") or []
    external = data.get("external") or []

    content_w = page_w - pad * 2
    y = 34.0
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    y += 36  # h1
    if subtitle:
        y += 28

    layer_title_ids: list[str] = []

    def add_layer(name: str, inner_nodes: list[dict[str, Any]], theme: tuple, lid: str) -> None:
        nonlocal y
        border, body, _t1, t2, fg = theme
        title_h = 36.0
        inner_bottom = max((n["y"] + n["h"] for n in inner_nodes), default=y + title_h + 26)
        layer_h = inner_bottom - y + 4
        nodes.append({
            "id": lid + "-title", "x": pad, "y": y, "w": content_w, "h": title_h,
            "text": name, "fill": t2, "stroke": border, "shape": "bar",
            "font_px": 15, "group": name,
        })
        layer_title_ids.append(lid + "-title")
        nodes.extend(inner_nodes)
        y += layer_h

    for i, layer in enumerate(layers):
        border, body, t1, t2, fg = LAYER_THEMES[i % len(LAYER_THEMES)]
        lname = str(layer.get("name") or f"层级{i+1}")
        lid = f"L{i}"
        modules = [m for m in (layer.get("modules") or []) if m]
        has_title = any(str(m.get("title") or "").strip() for m in modules)
        inner: list[dict[str, Any]] = []
        top = y + 36 + 12
        if has_title:
            group_count = min(max(len(modules), 1), 4)
            gw = (content_w - 28 - gap * (group_count - 1)) / group_count
            for j, mod in enumerate(modules):
                items = _normalize_items(mod.get("items"))
                cols = _chip_columns(group_count, items) if items else 1
                gx = pad + 14 + j * (gw + gap)
                gy = top + 24
                for k, item in enumerate(items):
                    col = k % cols
                    row = k // cols
                    cw = (gw - 20 - chip_gap * (cols - 1)) / cols
                    inner.append({
                        "id": f"{lid}-C{j}-{k}",
                        "x": gx + 10 + col * (cw + chip_gap),
                        "y": gy + row * (chip_h + chip_gap),
                        "w": cw, "h": chip_h,
                        "text": str(item), "fill": "#ffffff", "stroke": border,
                        "shape": "round", "font_px": layout["chip_font_px"], "group": lname,
                    })
        else:
            flat: list[str] = []
            for mod in modules:
                flat.extend(_normalize_items(mod.get("items")))
            cols = _chip_columns(1, flat, boxed=False) if flat else 1
            for k, item in enumerate(flat):
                col = k % cols
                row = k // cols
                cw = (content_w - 28 - chip_gap * (cols - 1)) / cols
                inner.append({
                    "id": f"{lid}-C{k}",
                    "x": pad + 14 + col * (cw + chip_gap),
                    "y": top + row * (chip_h + chip_gap),
                    "w": cw, "h": chip_h,
                    "text": str(item), "fill": "#ffffff", "stroke": border,
                    "shape": "round", "font_px": layout["chip_font_px"], "group": lname,
                })
        add_layer(lname, inner, (border, body, t1, t2, fg), lid)
        if i < len(layers) - 1:
            y += 26

    if external:
        y += 26
        ebd, ebody, et1, et2, efg = EXTERNAL_THEME
        cols = min(max(len(external), 1), 4)
        top = y + 36 + 12
        inner = []
        for k, ext in enumerate(external):
            col = k % cols
            row = k // cols
            cw = (content_w - 28 - chip_gap * (cols - 1)) / cols
            text = str(ext.get("title") or "外部系统")
            desc = str(ext.get("desc") or "")
            if desc:
                text = f"{text}\n{desc}"
            inner.append({
                "id": f"EXT-C{k}",
                "x": pad + 14 + col * (cw + chip_gap),
                "y": top + row * (44 + chip_gap),
                "w": cw, "h": 44,
                "text": text, "fill": "#ffffff", "stroke": ebd,
                "shape": "round", "font_px": 12.5, "group": "外部对接系统",
            })
        add_layer("外部对接系统", inner, (ebd, ebody, et1, et2, efg), "EXT")

    for a, b in zip(layer_title_ids, layer_title_ids[1:]):
        dashed = b.startswith("EXT")
        edges.append({"from": a, "to": b, "label": "", "dashed": dashed, "points": []})

    y += 40
    return {"title": title, "size": {"w": page_w, "h": math.ceil(y)}, "nodes": nodes, "edges": edges, "source": "json"}


def extract_ir_from_page(page: Any, title_fallback: str = "") -> Optional[dict[str, Any]]:
    """Producer B / DOM：从已渲染页面抽 GraphIR（截图同一坐标系）。"""
    try:
        ir = page.evaluate(EXTRACT_IR_JS)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(ir, dict):
        return None
    if not ir.get("title"):
        ir["title"] = title_fallback
    ir.setdefault("nodes", [])
    ir.setdefault("edges", [])
    ir.setdefault("size", {"w": 0, "h": 0})
    return ir


def ir_from_outputs(diagrams_dir: Path, stem: str) -> dict[str, Any]:
    """从已落盘产物重建 IR：优先 .ir.json，其次分层 .json，再次打开 HTML 抽取。"""
    ir_path = Path(diagrams_dir) / f"{stem}.ir.json"
    if ir_path.exists():
        return load_ir(ir_path)
    json_path = Path(diagrams_dir) / f"{stem}.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("layers"):
            return layered_json_to_ir(data)
    html_path = Path(diagrams_dir) / f"{stem}.html"
    if html_path.exists():
        from render_diagram import extract_ir_via_browser

        ir = extract_ir_via_browser(html_path)
        if ir and ir.get("nodes"):
            return ir
    raise FileNotFoundError(
        f"这张图缺少 html/json/ir，无法导出可编辑文件（{stem}）。请重新生成后再导出 draw.io / PPTX。"
    )


def node_by_id(ir: dict[str, Any], nid: str) -> Optional[dict[str, Any]]:
    for node in ir.get("nodes") or []:
        if node.get("id") == nid:
            return node
    return None


def sanitize_xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
