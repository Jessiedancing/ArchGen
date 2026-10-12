"""ArchGen 图表流水线：样式解析 + 输出自检 + 四件套导出。

被 archgen.py（CLI）、archgen_mcp.py（Agent 工具）与 main.py（内部测试台）共用。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

APP_NAME = "ArchGen"
VERSION = "0.4.0"
# 内置资源锚定到代码目录（T14.1）：MCP / 任意 cwd 调用都能找到，不再依赖当前工作目录
ENGINE_ROOT = Path(__file__).resolve().parent
STYLES_CONFIG = str(ENGINE_ROOT / "diagram_styles" / "styles.json")
DEFAULT_DIAGRAM_TITLE = "技术图表"
# 用户数据（输出目录）保持相对，相对调用方 cwd 解析（ADR 008），不锚定到代码目录
DEFAULT_OUTPUT_DIR = "diagrams"


def resource_path(rel: str) -> str:
    """把内置资源的相对路径锚定到代码目录，绝对路径原样返回（T14.1）。"""
    p = Path(rel)
    return str(p if p.is_absolute() else ENGINE_ROOT / p)

MERMAID_HEADERS = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "classDiagram",
    "journey",
    "mindmap",
    "C4Context",
)


def load_styles_config(path: str = STYLES_CONFIG) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "styles" not in data:
        raise ValueError(f"{path} 格式错误：需要 styles 字段")
    return data


def resolve_style(
    style_key: Optional[str],
    env: Optional[dict] = None,
    path: str = STYLES_CONFIG,
) -> tuple[str, dict]:
    cfg = load_styles_config(path)
    styles = cfg.get("styles") or {}
    env = env or {}
    key = (
        style_key
        or env.get("DIAGRAM_STYLE")
        or cfg.get("default")
        or "architecture"
    ).strip()
    if key not in styles:
        available = ", ".join(styles.keys())
        raise ValueError(f"未知样式「{key}」。可选：{available}")
    # system_prompt 是内置资源，锚定到代码目录，保证从任意 cwd 都能读到（T14.1）
    meta = dict(styles[key])
    if meta.get("system_prompt"):
        meta["system_prompt"] = resource_path(meta["system_prompt"])
    return key, meta


def style_name_hint(style_meta: dict) -> Optional[str]:
    return (
        style_meta.get("name_hint")
        or style_meta.get("output_stem")
        or style_meta.get("name")
    )


def styles_summary(path: str = STYLES_CONFIG) -> dict:
    """结构化样式清单，供 --json 与 Agent 工具使用。"""
    cfg = load_styles_config(path)
    return {
        "tool": APP_NAME,
        "version": VERSION,
        "default": cfg.get("default", ""),
        "standard_outputs": cfg.get("standard_outputs") or ["png", "html", "md", "mmd"],
        "naming": cfg.get("naming", "{名称}_{YYYYMMDD}_V{n}"),
        "styles": [
            {
                "key": key,
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "renderer": meta.get("renderer", "mermaid"),
                "use_when": meta.get("use_when", ""),
            }
            for key, meta in (cfg.get("styles") or {}).items()
        ],
    }


def print_styles_help(path: str = STYLES_CONFIG) -> None:
    cfg = load_styles_config(path)
    default = cfg.get("default", "")
    outputs = cfg.get("standard_outputs") or ["png", "html", "md", "mmd"]
    print(f"{APP_NAME} {VERSION}")
    print(f"默认样式：{default}")
    print(f"标准交付物（每次固定）：{', '.join(outputs)}")
    print(f"落盘命名：{cfg.get('naming', '{名称}_{YYYYMMDD}_V{n}')}")
    print("可用样式：")
    for key, meta in (cfg.get("styles") or {}).items():
        mark = " (default)" if key == default else ""
        print(f"  - {key}{mark}: {meta.get('name', '')} — {meta.get('description', '')}")
        if meta.get("use_when"):
            print(f"      适用: {meta['use_when']}")
        print(f"      renderer: {meta.get('renderer')}  system: {meta.get('system_prompt')}")


def _extract_mermaid(text: str) -> Optional[str]:
    match = re.search(r"```mermaid\s*\n(.*?)```", text, re.S | re.I)
    return match.group(1).strip() if match else None


def validate_mermaid(mermaid: str) -> list[str]:
    """轻量语法自检：抓最常见的不可渲染错误，不做完整解析。"""
    problems: list[str] = []
    raw_lines = [ln.strip() for ln in mermaid.splitlines() if ln.strip()]
    # T12 软校验：有 %% 图名才能让文件名反映主题，而不是退化成「流程图」
    has_title = any(re.match(r"^%%\s+(?!\{)\S+", ln) for ln in raw_lines[:8])
    if not has_title:
        problems.append("缺少图名：请在 Mermaid 代码第一行写「%% 中文图名」（不要用图种通名）")
    # 通名也不算有效图名
    generic = {"流程图", "时序图", "数据流图", "部署拓扑图", "状态机图", "实体关系图", "技术解析图", "架构图"}
    for ln in raw_lines[:8]:
        m = re.match(r"^%%\s+(.+)$", ln)
        if m and m.group(1).strip() in generic:
            problems.append("图名不能是图种通名，请写成具体主题（如「用户下单流程」）")
            break

    lines = [ln for ln in raw_lines if not ln.startswith("%%")]
    if not lines:
        return ["Mermaid 内容为空"]

    header = lines[0]
    if not any(header.startswith(h) for h in MERMAID_HEADERS):
        problems.append(f"首行不是合法图类型声明（当前：{header[:40]}）")

    opens = sum(1 for ln in lines if ln.startswith("subgraph"))
    closes = sum(1 for ln in lines if ln == "end")
    if opens != closes:
        problems.append(f"subgraph 与 end 不匹配（subgraph {opens} 个，end {closes} 个）")

    for ln in lines:
        if ln.count("[") != ln.count("]"):
            problems.append(f"方括号不配对：{ln[:60]}")
            break
    for ln in lines:
        if ln.count("(") != ln.count(")"):
            problems.append(f"圆括号不配对：{ln[:60]}")
            break

    # 节点标签里出现裸引号会让 mermaid 解析失败
    for ln in lines:
        if ln.count('"') % 2 == 1:
            problems.append(f"引号不配对：{ln[:60]}")
            break

    return problems


def validate_layered_json(text: str) -> list[str]:
    """架构样式：检查能否解析出带 layers 的 JSON。"""
    try:
        from llm_gateway import strip_reasoning

        cleaned = strip_reasoning(text)
    except Exception:  # noqa: BLE001
        cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return ["输出中找不到 JSON 对象"]
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        return [f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行）"]
    if not isinstance(data, dict) or not data.get("layers"):
        return ["JSON 缺少非空的 layers 字段"]
    if not isinstance(data.get("layers"), list):
        return ["layers 必须是数组"]
    for i, layer in enumerate(data["layers"], start=1):
        if not isinstance(layer, dict) or not layer.get("modules"):
            return [f"第 {i} 层缺少 modules"]
    return []


def validate_model_output(text: str, renderer: str) -> list[str]:
    """渲染前自检，返回问题列表；空列表表示可直接渲染。"""
    if renderer == "layered_html":
        return validate_layered_json(text)
    mermaid = _extract_mermaid(text)
    if not mermaid:
        return ["输出中没有 ```mermaid 代码块"]
    return validate_mermaid(mermaid)


def render_diagram_outputs(
    log_path: str,
    style_meta: dict,
    diagram_name: Optional[str] = None,
    out_dir: str = DEFAULT_OUTPUT_DIR,
    quiet: bool = False,
    with_drawio: bool = False,
    with_pptx: bool = False,
) -> Optional[dict]:
    """从模型输出日志导出四件套。失败时打印原因并返回 None。"""
    import sys

    err = sys.stderr

    try:
        from render_diagram import STANDARD_OUTPUTS, render_from_skill_log
    except Exception as exc:  # noqa: BLE001
        print(f"\n[渲染跳过] 无法导入 render_diagram：{exc}", file=err)
        return None

    try:
        paths = render_from_skill_log(
            log_path=log_path,
            title=style_meta.get("name", DEFAULT_DIAGRAM_TITLE),
            renderer=style_meta.get("renderer", "mermaid"),
            name_hint=style_name_hint(style_meta),
            diagram_name=diagram_name,
            diagrams_dir=Path(out_dir),
            with_drawio=with_drawio,
            with_pptx=with_pptx,
        )
    except Exception as exc:  # noqa: BLE001
        from render_diagram import RenderError, classify_render_error, log_render_failure

        classified = classify_render_error(exc)
        try:
            log_render_failure(log_path, classified)
        except Exception:  # noqa: BLE001
            pass
        print(f"\n[渲染失败] {classified}", file=err)
        print("可稍后单独执行：archgen --render-only --style <样式名>", file=err)
        raise RenderError(classified.kind, str(classified), classified.detail) from exc

    if not quiet:
        _print_paths(paths, STANDARD_OUTPUTS)
    return paths


def _print_paths(paths: dict, standard_outputs) -> None:
    version_stem = paths.get("stem")
    print("\n>>> 已导出图表（标准四件套）：")
    if version_stem:
        print(f"    版本名: {version_stem}  （格式：名称_日期_Vn）")
    for kind in standard_outputs:
        if kind in paths:
            print(f"    {kind}: {paths[kind]}")
    for kind, path in paths.items():
        if kind not in standard_outputs and kind != "stem":
            print(f"    {kind}: {path}")


def base_name_from_stem(stem: str) -> str:
    """把「订单流程_20260908_V2」还原成「订单流程」，便于改图后续到 V3。"""
    return re.sub(r"_\d{8}_V\d+$", "", stem) or stem


def render_source_file(
    source_path: str,
    style_meta: Optional[dict] = None,
    diagram_name: Optional[str] = None,
    out_dir: str = DEFAULT_OUTPUT_DIR,
    quiet: bool = False,
    with_drawio: bool = False,
    with_pptx: bool = False,
    log_path: Optional[str] = None,
) -> Optional[dict]:
    """从已导出的 .mmd / .json 手工改稿重新出图，不调用模型。

    .json 走分层架构渲染；.mmd / .md 按 Mermaid 渲染。
    默认沿用原文件名并递增版本号，旧图不会被覆盖。
    """
    import sys

    err = sys.stderr
    path = Path(source_path)
    if not path.exists():
        print(f"\n[渲染失败] 找不到文件：{path}", file=err)
        return None

    try:
        from render_diagram import STANDARD_OUTPUTS, render_from_assistant_text
    except Exception as exc:  # noqa: BLE001
        print(f"\n[渲染跳过] 无法导入 render_diagram：{exc}", file=err)
        return None

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        renderer = "layered_html"
        assistant_text = text
    else:
        renderer = "mermaid"
        assistant_text = text if "```mermaid" in text else f"```mermaid\n{text}\n```"

    style_meta = style_meta or {}
    try:
        paths = render_from_assistant_text(
            assistant_text,
            renderer=renderer,
            title=style_meta.get("name", DEFAULT_DIAGRAM_TITLE),
            name_hint=style_name_hint(style_meta),
            diagram_name=diagram_name or base_name_from_stem(path.stem),
            diagrams_dir=Path(out_dir),
            with_drawio=with_drawio,
            with_pptx=with_pptx,
        )
    except Exception as exc:  # noqa: BLE001
        from render_diagram import RenderError, classify_render_error, log_render_failure

        classified = classify_render_error(exc)
        if log_path:
            try:
                log_render_failure(log_path, classified)
            except Exception:  # noqa: BLE001
                pass
        print(f"\n[渲染失败] {classified}", file=err)
        raise RenderError(classified.kind, str(classified), classified.detail) from exc

    if not quiet:
        _print_paths(paths, STANDARD_OUTPUTS)
    return paths
