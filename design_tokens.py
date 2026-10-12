"""设计 token 单一来源加载器（ADR 012 / T05）。

`design_tokens.json` 是唯一配色/字体来源，本模块把它派生成各下游需要的形态：

- `ui_css()`            → 桌面 UI 的 `:root{}` CSS 变量（desktop 动态 `/tokens.css`）
- `layer_themes()`     → `render_diagram.LAYER_THEMES`（架构图分层色）
- `mermaid_config()`   → Mermaid `theme:"base"` 的 `themeVariables`（T01）
- `shape_colors()`     → drawio / pptx 形状填充与描边（T04 / T06）

改配色只改 JSON 一处，UI 与新出的图同时变。文件缺失时回退内置默认，保证不崩。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ENGINE_ROOT = Path(__file__).resolve().parent
TOKENS_PATH = ENGINE_ROOT / "design_tokens.json"

_GENERIC_FAMILIES = {
    "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
    "sans-serif", "serif", "monospace", "-apple-system", "cursive", "fantasy",
}

# 文件缺失时的兜底（与 design_tokens.json 保持一致的最小集），避免渲染/UI 崩
_FALLBACK: dict[str, Any] = {
    "fonts": {
        "ui": ["Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", "sans-serif"],
        "display": ["Segoe UI", "PingFang SC", "Microsoft YaHei", "sans-serif"],
        "mono": ["Consolas", "Menlo", "monospace"],
    },
    "ui": {
        "bg": "#eef3fb", "panel": "#ffffff", "ink": "#1f2a37", "muted": "#64748b",
        "line": "#dbe6f3", "accent": "#2563eb", "accent-ink": "#ffffff",
        "accent-soft": "#e7effe", "warn": "#c2410c", "radius": "10px",
    },
    "mermaid": {"theme": "base", "themeVariables": {}},
    "shape": {"fill": "#e7effe", "stroke": "#6ea8dc", "text": "#17427e"},
    "layers": [
        {"border": "#6ea8dc", "body": "#f2f8ff", "title1": "#cfe4fb", "title2": "#e9f3fe", "fg": "#1a4d8f"},
        {"border": "#77bd76", "body": "#f3fbf3", "title1": "#d5f0d2", "title2": "#eaf8e8", "fg": "#22662a"},
        {"border": "#6fa8d8", "body": "#f2f8ff", "title1": "#cbe2f7", "title2": "#e7f2fc", "fg": "#17508c"},
        {"border": "#6ab5c4", "body": "#f1fbfc", "title1": "#cbeaf0", "title2": "#e7f7fa", "fg": "#125e6b"},
        {"border": "#a98cd8", "body": "#faf6ff", "title1": "#e4d9f6", "title2": "#f2ecfb", "fg": "#553a94"},
        {"border": "#e0a86a", "body": "#fff8f0", "title1": "#fbe3c8", "title2": "#fdf1e2", "fg": "#8a5116"},
    ],
    "external_layer": {"border": "#94a3b8", "body": "#fafafa", "title1": "#e8ecf1", "title2": "#f3f5f8", "fg": "#41546b"},
    "page": {
        "width": 1180, "padding": 38, "chip_font_px": 12.5,
        "chip_pad_px": 18, "layer_border_px": 3, "groups_pad_x": 28,
        "group_gap": 12, "group_box_inset": 22, "chip_gap": 8, "max_chip_cols": 5,
        "pptx_width_in": 13.333, "pptx_height_in": 7.5, "pptx_margin_in": 0.4,
    },
}

_CACHE: Optional[dict[str, Any]] = None


def load_tokens(force: bool = False) -> dict[str, Any]:
    """读取并缓存 design_tokens.json；缺失或损坏时回退内置默认。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    data: dict[str, Any]
    try:
        data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("design_tokens.json 根节点须为对象")
    except (OSError, ValueError, json.JSONDecodeError):
        data = _FALLBACK
    _CACHE = data
    return data


def font_stack(kind: str = "ui") -> str:
    """把字体列表拼成合法 CSS font-family 串（多词加引号，通用族不加）。"""
    fonts = load_tokens().get("fonts", {})
    names = fonts.get(kind) or _FALLBACK["fonts"].get(kind, ["sans-serif"])
    parts = []
    for name in names:
        if name in _GENERIC_FAMILIES or " " not in name:
            parts.append(name)
        else:
            parts.append(f'"{name}"')
    return ", ".join(parts)


def _layer_tuple(layer: dict[str, str]) -> tuple[str, str, str, str, str]:
    """(border, body, title1, title2, fg)——对齐 render_diagram.LAYER_THEMES 顺序。"""
    return (layer["border"], layer["body"], layer["title1"], layer["title2"], layer["fg"])


def layer_themes() -> list[tuple[str, str, str, str, str]]:
    layers = load_tokens().get("layers") or _FALLBACK["layers"]
    return [_layer_tuple(x) for x in layers]


def external_layer_theme() -> tuple[str, str, str, str, str]:
    ext = load_tokens().get("external_layer") or _FALLBACK["external_layer"]
    return _layer_tuple(ext)


def mermaid_config() -> dict[str, Any]:
    """Mermaid `initialize` 所需片段：theme + themeVariables + flowchart 间距（T01）。"""
    tokens = load_tokens()
    mermaid = dict(tokens.get("mermaid") or {})
    variables = dict(mermaid.get("themeVariables") or {})
    variables.setdefault("fontFamily", font_stack("ui"))
    flow = dict(mermaid.get("flowchart") or {})
    flow.setdefault("htmlLabels", True)
    flow.setdefault("curve", "basis")
    flow.setdefault("padding", 16)
    flow.setdefault("nodeSpacing", 48)
    flow.setdefault("rankSpacing", 56)
    return {
        "theme": mermaid.get("theme", "base"),
        "themeVariables": variables,
        "flowchart": flow,
    }


def shape_colors() -> dict[str, str]:
    return dict(load_tokens().get("shape") or _FALLBACK["shape"])


def page_config() -> dict[str, Any]:
    return dict(load_tokens().get("page") or _FALLBACK["page"])


def ui_css() -> str:
    """生成桌面 UI 的 `:root{}` CSS 变量块，由 design_tokens 派生。"""
    tokens = load_tokens()
    ui = tokens.get("ui") or _FALLBACK["ui"]
    lines = ["/* 由 design_tokens.json 派生，请勿手改（ADR 012 / T05） */", ":root {"]
    for key, value in ui.items():
        lines.append(f"  --{key}: {value};")
    lines.append(f"  --ui: {font_stack('ui')};")
    lines.append(f"  --font: {font_stack('display')};")
    lines.append(f"  --mono: {font_stack('mono')};")
    lines.append("}")
    return "\n".join(lines) + "\n"
