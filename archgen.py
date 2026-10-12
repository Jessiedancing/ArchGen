#!/usr/bin/env python3
"""ArchGen · 私有模型技术图表生成器。

把一段文本变成架构图 / 流程图 / 时序图 / 数据流图 / 部署拓扑 / 状态机，
固定导出 png + html + md + mmd，文件名按「名称_日期_V版本」管理。
推理只发往 .env 中的 BASE_URL。

用法：
    python3 archgen.py --input doc.txt --style architecture
    python3 archgen.py --list-styles
    python3 archgen.py --render-only --style flowchart
    python3 archgen.py -i doc.txt --json      # 供 Agent 调用，stdout 为纯 JSON
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

from diagram_pipeline import (
    APP_NAME,
    DEFAULT_OUTPUT_DIR,
    VERSION,
    print_styles_help,
    render_diagram_outputs,
    render_source_file,
    resolve_style,
    styles_summary,
)
from llm_gateway import (
    build_client,
    load_env,
    prepend_record,
    print_model_help,
    read_sampling,
    read_text,
    resolve_model,
    stream_completion,
)

DEFAULT_INPUT = "input.txt"
DEFAULT_LOG = "logs/archgen_output.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archgen",
        description=f"{APP_NAME} · 用私有模型把文本变成技术图表，固定导出 png/html/md/mmd。",
    )
    parser.add_argument("--input", "-i", default=DEFAULT_INPUT, help=f"输入文本文件（默认 {DEFAULT_INPUT}）")
    parser.add_argument("--style", "-s", default=None, help="图表样式，见 --list-styles")
    parser.add_argument("--model", "-m", default=None, help="覆盖 .env 的 MODEL，可用别名")
    parser.add_argument("--name", "-n", default=None, help="导出文件名前缀，默认按图标题自动命名")
    parser.add_argument("--out-dir", "-o", default=DEFAULT_OUTPUT_DIR, help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--log", default=DEFAULT_LOG, help=f"模型原始输出记录（默认 {DEFAULT_LOG}）")
    parser.add_argument("--text", "-t", default=None, help="直接传入文本，替代 --input")
    parser.add_argument("--list-styles", action="store_true", help="列出可用样式与交付格式")
    parser.add_argument("--list-models", action="store_true", help="列出 .env 模型并探测权限")
    parser.add_argument("--render-only", action="store_true", help="不调模型，用上一次的模型结果重新导出")
    parser.add_argument(
        "--from-file",
        "-f",
        default=None,
        help="不调模型，直接渲染手工改过的 .mmd / .json",
    )
    parser.add_argument("--no-render", action="store_true", help="只生成文本结果，不导出图片")
    parser.add_argument("--json", action="store_true", help="stdout 只输出 JSON 结果，便于 Agent 调用")
    parser.add_argument("--retries", type=int, default=1, help="Mermaid 语法自检失败后的重试次数（默认 1）")
    parser.add_argument("--with-drawio", action="store_true", help="额外导出可编辑 .drawio（按需，T04）")
    parser.add_argument("--with-pptx", action="store_true", help="额外导出可编辑 .pptx（按需，T06；需 python-pptx）")
    parser.add_argument(
        "--profile",
        default=None,
        help="读取 .env.<name>，不存在则回退 .env（T07 / ADR 013）",
    )
    parser.add_argument("--version", "-v", action="version", version=f"{APP_NAME} {VERSION}")
    return parser


def _log(message: str, quiet: bool) -> None:
    print(message, file=sys.stderr if quiet else sys.stdout)


def generate(
    source_text: str,
    source_label: str,
    style_meta: dict,
    style_key: str,
    model_override: str | None,
    log_path: str,
    env: dict,
    quiet: bool = False,
    retries: int = 1,
) -> str:
    """调模型出图源码，Mermaid 样式会做语法自检并按需重试。"""
    from diagram_pipeline import validate_model_output

    system_prompt = read_text(style_meta["system_prompt"])
    client, base_url = build_client(env)
    model = resolve_model(model_override, env)
    temperature, seed = read_sampling(env)

    _log(f">>> 样式：{style_key}（{style_meta.get('name', '')}）", quiet)
    _log(f">>> 模型：{model}", quiet)
    _log(f">>> 网关：{base_url}", quiet)
    _log(f">>> 输入：{source_label}\n", quiet)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": source_text},
    ]

    output = ""
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        output = stream_completion(
            client,
            model,
            messages,
            temperature=temperature,
            seed=seed,
            echo=not quiet,
        )
        problems = validate_model_output(output, style_meta.get("renderer", "mermaid"))
        if not problems:
            break
        if attempt == attempts:
            _log(f"\n[自检] 仍有问题，直接尝试渲染：{'；'.join(problems)}", quiet)
            break
        _log(f"\n[自检] 第 {attempt} 次输出有问题，正在让模型修正：{'；'.join(problems)}", quiet)
        messages = messages + [
            {"role": "assistant", "content": output},
            {
                "role": "user",
                "content": (
                    "上一版输出存在以下问题，请修正后重新完整输出，"
                    "不要解释、不要保留错误内容：\n- " + "\n- ".join(problems)
                ),
            },
        ]

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = (
        f"\n{'=' * 60}\n"
        f"[时间] {timestamp}\n"
        f"[工具] {APP_NAME} {VERSION}\n"
        f"[样式] {style_key}\n"
        f"[模型] {model}\n"
        f"[地址] {base_url}\n"
        f"[输入] {source_label}\n"
        f"{'-' * 60}\n"
        f"[assistant]\n"
        f"{output if output.endswith(chr(10)) else output + chr(10)}\n"
    )
    prepend_record(log_path, record)
    _log(f"\n>>> 模型输出已记录：{log_path}", quiet)
    return output


def _emit_result(paths: dict | None, style_key: str, args) -> None:
    """统一收尾：--json 时输出结构化结果，否则失败即退出码 1。"""
    if args.json:
        if paths is None:
            print(json.dumps({"ok": False, "style": style_key, "error": "渲染失败，详见 stderr"}, ensure_ascii=False))
            sys.exit(1)
        payload = {
            "ok": True,
            "tool": APP_NAME,
            "version": VERSION,
            "style": style_key,
            "stem": str(paths.get("stem", "")),
            "files": {k: str(v) for k, v in paths.items() if k != "stem"},
            "log": args.log,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if paths is None:
        sys.exit(1)


def main() -> None:
    args = build_parser().parse_args()
    quiet = args.json

    if args.list_styles:
        if args.json:
            print(json.dumps(styles_summary(), ensure_ascii=False, indent=2))
        else:
            print_styles_help()
        return

    env = load_env(profile=args.profile)

    if args.list_models:
        try:
            client, _ = build_client(env)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
        temperature, _ = read_sampling(env)
        print_model_help(env, client, temperature)
        return

    try:
        style_key, style_meta = resolve_style(args.style, env)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    if args.from_file:
        try:
            paths = render_source_file(
                args.from_file,
                style_meta=style_meta if args.style else None,
                diagram_name=args.name,
                out_dir=args.out_dir,
                quiet=quiet,
                with_drawio=args.with_drawio,
                with_pptx=args.with_pptx,
                log_path=args.log,
            )
        except Exception as exc:  # noqa: BLE001 — RenderError 已打印
            from render_diagram import RenderError

            if isinstance(exc, RenderError) and args.json:
                print(json.dumps({"ok": False, "style": style_key, "error": str(exc), "kind": exc.kind}, ensure_ascii=False))
                sys.exit(1)
            if not isinstance(exc, RenderError):
                print(str(exc), file=sys.stderr)
            sys.exit(1)
        _emit_result(paths, style_key, args)
        return

    if not args.render_only:
        if args.text:
            source_text, source_label = args.text, "(--text 直接输入)"
        else:
            if not Path(args.input).exists():
                print(
                    f"找不到输入文件：{args.input}\n"
                    f"请准备一份文本（可参考 examples/sample_input.txt），或用 --input / --text 指定。",
                    file=sys.stderr,
                )
                sys.exit(2)
            source_text, source_label = read_text(args.input), args.input

        try:
            generate(
                source_text,
                source_label,
                style_meta,
                style_key,
                args.model,
                args.log,
                env,
                quiet=quiet,
                retries=max(0, args.retries),
            )
        except (ValueError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)

        if args.no_render:
            if args.json:
                print(json.dumps({"ok": True, "style": style_key, "log": args.log}, ensure_ascii=False))
            return

    try:
        paths = render_diagram_outputs(
            args.log,
            style_meta,
            diagram_name=args.name,
            out_dir=args.out_dir,
            quiet=quiet,
            with_drawio=args.with_drawio,
            with_pptx=args.with_pptx,
        )
    except Exception as exc:  # noqa: BLE001
        from render_diagram import RenderError

        if isinstance(exc, RenderError) and args.json:
            print(json.dumps({"ok": False, "style": style_key, "error": str(exc), "kind": exc.kind}, ensure_ascii=False))
            sys.exit(1)
        if not isinstance(exc, RenderError):
            print(str(exc), file=sys.stderr)
        sys.exit(1)

    _emit_result(paths, style_key, args)


if __name__ == "__main__":
    main()
