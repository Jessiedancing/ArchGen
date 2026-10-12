#!/usr/bin/env python3
"""ArchGen MCP 服务：让支持 MCP 的 Agent 工具直接调用画图能力。

零依赖实现（stdio + JSON-RPC 2.0），可挂到 Codex、Cursor 等任何 MCP 客户端：

    {
      "mcpServers": {
        "archgen": { "command": "python3", "args": ["/abs/path/archgen_mcp.py"] }
      }
    }

暴露三个工具：
- archgen_list_styles  列出可用图种
- archgen_create       文本 → 图表（固定四件套）
- archgen_rerender     不调模型，重新导出上次结果
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diagram_pipeline import (  # noqa: E402
    APP_NAME,
    DEFAULT_OUTPUT_DIR,
    VERSION,
    render_diagram_outputs,
    resolve_style,
    styles_summary,
)

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_LOG = "logs/archgen_output.txt"

TOOLS = [
    {
        "name": "archgen_list_styles",
        "description": "列出 ArchGen 支持的图表类型（架构图/流程图/时序图/数据流图/部署拓扑/状态机/ER），以及固定导出的文件格式与命名规则。画图前先调用它选型。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "archgen_create",
        "description": "把一段技术文本变成图表，用私有模型推理，固定导出 png/html/md/mmd 四种格式，文件名按 名称_日期_V版本 管理。返回各文件绝对路径。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要画图的原文，越具体越准确"},
                "style": {
                    "type": "string",
                    "description": "图表类型 key，如 architecture / flowchart / sequence / dataflow / deployment / state / er；不传用默认",
                },
                "name": {"type": "string", "description": "文件名前缀，不传则按图标题自动命名"},
                "model": {"type": "string", "description": "覆盖默认模型，可用 .env 中 MODELS 的别名"},
                "out_dir": {"type": "string", "description": f"输出目录，默认 {DEFAULT_OUTPUT_DIR}"},
                "with_drawio": {"type": "boolean", "description": "额外导出可编辑 .drawio"},
                "with_pptx": {"type": "boolean", "description": "额外导出可编辑 .pptx（需 python-pptx）"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "archgen_rerender",
        "description": "不调用模型，仅根据上一次模型输出重新导出四件套。适合改完 .mmd 或换输出目录后重跑。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "style": {"type": "string", "description": "图表类型 key，需与上次一致"},
                "name": {"type": "string", "description": "文件名前缀"},
                "out_dir": {"type": "string", "description": f"输出目录，默认 {DEFAULT_OUTPUT_DIR}"},
                "log": {"type": "string", "description": f"模型输出日志路径，默认 {DEFAULT_LOG}"},
                "with_drawio": {"type": "boolean", "description": "额外导出可编辑 .drawio"},
                "with_pptx": {"type": "boolean", "description": "额外导出可编辑 .pptx（需 python-pptx）"},
            },
            "required": [],
        },
    },
]


def _text_result(payload: object, is_error: bool = False) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": body}], "isError": is_error}


def _format_paths(paths: dict, style_key: str) -> dict:
    files = {k: str(Path(v).resolve()) for k, v in paths.items() if k != "stem"}
    return {
        "ok": True,
        "tool": APP_NAME,
        "style": style_key,
        "stem": str(paths.get("stem", "")),
        "files": files,
        "note": "png/html/md/mmd 为固定四件套；drawio/pptx 仅在请求 with_drawio / with_pptx 时生成",
    }


def tool_list_styles(_: dict) -> dict:
    return _text_result(styles_summary())


def tool_create(args: dict) -> dict:
    from archgen import generate
    from llm_gateway import load_env

    text = (args.get("text") or "").strip()
    if not text:
        return _text_result({"ok": False, "error": "text 不能为空"}, is_error=True)

    env = load_env()
    style_key, style_meta = resolve_style(args.get("style"), env)
    log_path = args.get("log") or DEFAULT_LOG

    generate(
        text,
        "(MCP 调用)",
        style_meta,
        style_key,
        args.get("model"),
        log_path,
        env,
        quiet=True,
    )
    from render_diagram import RenderError

    try:
        paths = render_diagram_outputs(
            log_path,
            style_meta,
            diagram_name=args.get("name"),
            out_dir=args.get("out_dir") or DEFAULT_OUTPUT_DIR,
            quiet=True,
            with_drawio=bool(args.get("with_drawio")),
            with_pptx=bool(args.get("with_pptx")),
        )
    except RenderError as exc:
        return _text_result(
            {"ok": False, "style": style_key, "error": str(exc), "kind": exc.kind},
            is_error=True,
        )
    if paths is None:
        return _text_result(
            {"ok": False, "style": style_key, "error": "渲染失败，详情已写入日志"},
            is_error=True,
        )
    return _text_result(_format_paths(paths, style_key))


def tool_rerender(args: dict) -> dict:
    from llm_gateway import load_env

    env = load_env()
    style_key, style_meta = resolve_style(args.get("style"), env)
    from render_diagram import RenderError

    try:
        paths = render_diagram_outputs(
            args.get("log") or DEFAULT_LOG,
            style_meta,
            diagram_name=args.get("name"),
            out_dir=args.get("out_dir") or DEFAULT_OUTPUT_DIR,
            quiet=True,
            with_drawio=bool(args.get("with_drawio")),
            with_pptx=bool(args.get("with_pptx")),
        )
    except RenderError as exc:
        return _text_result({"ok": False, "style": style_key, "error": str(exc), "kind": exc.kind}, is_error=True)
    if paths is None:
        return _text_result({"ok": False, "style": style_key, "error": "重新导出失败，详情已写入日志"}, is_error=True)
    return _text_result(_format_paths(paths, style_key))


HANDLERS = {
    "archgen_list_styles": tool_list_styles,
    "archgen_create": tool_create,
    "archgen_rerender": tool_rerender,
}


def handle(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": APP_NAME.lower(), "version": VERSION},
        }
    elif method in ("notifications/initialized", "initialized"):
        return None
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"未知工具：{name}"},
            }
        try:
            result = handler(params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001
            print(traceback.format_exc(), file=sys.stderr)
            result = _text_result({"ok": False, "error": str(exc)}, is_error=True)
    elif method == "ping":
        result = {}
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"未实现的方法：{method}"},
        }

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
