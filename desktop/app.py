#!/usr/bin/env python3
"""ArchGen 本地绿色版 · 仅监听 127.0.0.1 的轻量 Web UI。

复用仓库根目录的 llm_gateway / diagram_pipeline / render_diagram，
配置与产出落在 userdata/，与代码目录隔离。
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

DESKTOP_DIR = Path(__file__).resolve().parent
# 绿色包：desktop 的上一级即引擎根；开发时也是仓库根
ENGINE_ROOT = DESKTOP_DIR.parent
STATIC_DIR = DESKTOP_DIR / "static"


def _dir_writable(path: Path) -> bool:
    """探测目录可写：能建目录并落一个探针文件才算数（T14.2）。

    仅判断存在性不够——`C:\\Program Files\\` 下目录可能存在但拒绝写入。
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".archgen_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False


def _platform_userdata_base() -> Path:
    """系统级用户数据目录（不可写包内目录时的回退，T14.2）。"""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "ArchGen"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ArchGen"
    # Linux / 其他：遵循 XDG
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "ArchGen"


def resolve_userdata_dir() -> Path:
    """决定 userdata 实际落盘位置（T14.2）。

    优先级：环境变量 ARCHGEN_USERDATA > 包内 userdata（可写时）> 系统用户数据目录。
    绿色包被解压到 Program Files / 只读介质时，自动回退到系统目录，出图与配置不再失败。
    """
    override = os.environ.get("ARCHGEN_USERDATA")
    if override:
        return Path(override).expanduser().resolve()

    in_package = ENGINE_ROOT / "userdata"
    if _dir_writable(in_package):
        return in_package

    fallback = _platform_userdata_base()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


USERDATA_DIR = resolve_userdata_dir()
CONFIG_PATH = USERDATA_DIR / "config.json"
# 产出目录保持 userdata/diagrams（D-02 / ADR 008）：改名会让升级后历史图从界面消失
DIAGRAMS_DIR = USERDATA_DIR / "diagrams"
LOGS_DIR = USERDATA_DIR / "logs"
LOG_PATH = LOGS_DIR / "archgen_output.txt"

DEFAULT_PORT = 8765
HOST = "127.0.0.1"

SETTING_KEYS = (
    "OPENAI_API_KEY",
    "BASE_URL",
    "MODEL",
    "MODELS",
    "SSL_VERIFY",
    "API_VERSION",
    "TEMPERATURE",
    "SEED",
    "DIAGRAM_STYLE",
    "REQUEST_TIMEOUT",
    "TRUST_ENV",
    "PROXY",
)
PROFILE_META_KEYS = ("label",)


def _ensure_dirs() -> None:
    USERDATA_DIR.mkdir(parents=True, exist_ok=True)
    DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _bootstrap_engine() -> None:
    """把引擎根加入 sys.path。

    内置资源（styles.json / 样式 prompt / vendor）已在各模块按 ENGINE_ROOT 锚定
    绝对路径（T14.1），不再需要 os.chdir()——多线程 HTTP server 里改全局 cwd 并不干净。
    用户数据（USERDATA_DIR / DIAGRAMS_DIR）本就是绝对路径。
    """
    root = str(ENGINE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _safe_profile_key(name: str) -> str:
    import re

    key = re.sub(r"[^\w\-]+", "-", str(name or "").strip(), flags=re.UNICODE).strip("-")
    if not key:
        raise ValueError("档位名不能为空")
    return key


def _profile_fields(raw: dict) -> dict[str, str]:
    data: dict[str, str] = {}
    for key in SETTING_KEYS + PROFILE_META_KEYS:
        val = raw.get(key)
        if val is not None and str(val).strip() != "":
            data[key] = str(val)
    return data


def _import_env_defaults() -> dict[str, str]:
    env_file = ENGINE_ROOT / ".env"
    if not env_file.exists():
        return {}
    from llm_gateway import load_env

    env = load_env(str(env_file))
    data: dict[str, str] = {}
    for key in SETTING_KEYS:
        if env.get(key):
            data[key] = str(env[key])
    return data


def _empty_profile(label: str = "默认") -> dict[str, str]:
    profile = _import_env_defaults()
    profile.setdefault("label", label)
    profile.setdefault("REQUEST_TIMEOUT", "120")
    profile.setdefault("TRUST_ENV", "false")
    return profile


def load_config() -> dict[str, Any]:
    """读 `{active, profiles{}}`；旧扁平配置包装为 default 并回写（T07）。"""
    _ensure_dirs()
    raw: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (json.JSONDecodeError, OSError):
            raw = {}

    if isinstance(raw.get("profiles"), dict) and raw["profiles"]:
        profiles = {str(k): _profile_fields(v) if isinstance(v, dict) else {} for k, v in raw["profiles"].items()}
        active = str(raw.get("active") or next(iter(profiles)))
        if active not in profiles:
            active = next(iter(profiles))
        cfg = {"active": active, "profiles": profiles}
        return cfg

    migrated = _profile_fields(raw) if raw else {}
    if not migrated.get("BASE_URL"):
        migrated.update({k: v for k, v in _empty_profile().items() if k not in migrated})
    migrated.setdefault("label", "默认")
    cfg = {"active": "default", "profiles": {"default": migrated}}
    save_config(cfg)
    return cfg


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    _ensure_dirs()
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cfg


def load_settings() -> dict[str, str]:
    cfg = load_config()
    return dict(cfg["profiles"].get(cfg["active"]) or {})


def save_settings(payload: dict[str, Any]) -> dict[str, str]:
    from llm_gateway import validate_base_url

    cfg = load_config()
    active = cfg["active"]
    current = dict(cfg["profiles"].get(active) or {})
    for key in SETTING_KEYS + PROFILE_META_KEYS:
        if key in payload and payload[key] is not None:
            current[key] = str(payload[key]).strip()
    if "BASE_URL" in current:
        problem = validate_base_url(current["BASE_URL"])
        if problem:
            raise ValueError(problem)
    cfg["profiles"][active] = current
    save_config(cfg)
    return current


def settings_as_env(profile: Optional[str] = None) -> dict:
    """把当前（或指定）档位合成 llm_gateway 可用的 env 字典。"""
    from llm_gateway import load_env

    env = load_env(str(ENGINE_ROOT / ".env")) if (ENGINE_ROOT / ".env").exists() else dict(os.environ)
    cfg = load_config()
    name = profile or cfg["active"]
    if name not in cfg["profiles"]:
        raise ValueError(f"没有档位「{name}」")
    for key, val in cfg["profiles"][name].items():
        if key != "label":
            env[key] = val
    return env


def find_free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"找不到可用端口（从 {start} 起试了 40 个）")


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def _safe_file_under(root: Path, rel: str) -> Path:
    """防止路径穿越：只允许读 diagrams 下的文件。"""
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if not str(target).startswith(str(root_resolved) + os.sep) and target != root_resolved:
        raise PermissionError("不允许访问该路径")
    if not target.is_file():
        raise FileNotFoundError(str(target))
    return target


def api_meta() -> dict:
    from diagram_pipeline import APP_NAME, VERSION

    return {
        "tool": APP_NAME,
        "version": VERSION,
        "engine_root": str(ENGINE_ROOT),
        "userdata": str(USERDATA_DIR),
        "diagrams_dir": str(DIAGRAMS_DIR),
        "config_path": str(CONFIG_PATH),
    }


def api_styles() -> dict:
    from diagram_pipeline import styles_summary

    return styles_summary()


def api_history(limit: int = 40) -> dict:
    _ensure_dirs()
    items: list[dict] = []
    files = sorted(
        DIAGRAMS_DIR.glob("*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files[:limit]:
        stem = path.stem
        row = {
            "stem": stem,
            "png": stem + ".png",
            "mtime": int(path.stat().st_mtime),
            "preview_url": f"/api/files/{urllib.parse.quote(stem + '.png')}",
        }
        for ext in ("html", "md", "mmd", "json", "drawio", "pptx", "ir.json"):
            sibling = DIAGRAMS_DIR / f"{stem}.{ext}"
            if sibling.exists():
                row[ext] = sibling.name
        items.append(row)
    return {"items": items, "dir": str(DIAGRAMS_DIR)}


def _probe_one_env(env: dict) -> dict:
    from llm_gateway import (
        build_client,
        classify_probe_failure,
        parse_model_catalog,
        probe_model,
        read_sampling,
        validate_base_url,
    )

    base_url = (env.get("BASE_URL") or "").strip()
    problem = validate_base_url(base_url)
    if problem:
        raise ValueError(f"地址格式不对：{problem}")
    try:
        client, base_url = build_client(env)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(classify_probe_failure(exc, base_url)) from exc
    temperature, _ = read_sampling(env)
    catalog = parse_model_catalog(env)
    default_model = (env.get("MODEL") or "").strip()
    names = sorted({name for name in catalog.values()})
    if not names and default_model:
        names = [default_model]
    results = []
    for name in names:
        ok, msg = probe_model(client, name, temperature=temperature)
        if not ok:
            from llm_gateway import classify_probe_failure

            msg = classify_probe_failure(RuntimeError(msg), base_url)
        results.append(
            {
                "model": name,
                "ok": ok,
                "detail": msg if ok else msg.split("\n")[0][:280],
            }
        )
    return {
        "ok": True,
        "base_url": base_url,
        "default_model": default_model,
        "results": results,
    }


def api_probe(payload: Optional[dict] = None) -> dict:
    payload = payload or {}
    cfg = load_config()
    if payload.get("all"):
        rows = []
        for name in cfg["profiles"]:
            try:
                row = _probe_one_env(settings_as_env(name))
                row["profile"] = name
                row["label"] = cfg["profiles"][name].get("label") or name
                rows.append(row)
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "profile": name,
                        "label": cfg["profiles"][name].get("label") or name,
                        "ok": False,
                        "error": str(exc),
                        "results": [],
                    }
                )
        return {"ok": True, "probes": rows, "active": cfg["active"]}
    target = (payload.get("profile") or "").strip() or cfg["active"]
    result = _probe_one_env(settings_as_env(target))
    result["profile"] = target
    return result


def api_models() -> dict:
    from llm_gateway import build_client, list_gateway_models, parse_model_catalog

    env = settings_as_env()
    catalog = parse_model_catalog(env)
    names = sorted({name for name in catalog.values()})
    remote: list[str] = []
    try:
        from llm_gateway import validate_base_url

        problem = validate_base_url(env.get("BASE_URL") or "")
        if problem:
            return {"ok": True, "models": names, "default": (env.get("MODEL") or "").strip(), "hint": problem}
        client, _ = build_client(env)
        remote = list_gateway_models(client)
    except Exception:  # noqa: BLE001
        remote = []
    merged = []
    seen = set()
    for name in names + remote:
        if name and name not in seen:
            seen.add(name)
            merged.append(name)
    return {"ok": True, "models": merged, "default": (env.get("MODEL") or "").strip()}


def api_profiles_payload() -> dict:
    cfg = load_config()
    return {
        "ok": True,
        "active": cfg["active"],
        "profiles": {
            name: {"label": (prof.get("label") or name)}
            for name, prof in cfg["profiles"].items()
        },
        "settings": dict(cfg["profiles"].get(cfg["active"]) or {}),
    }


def api_switch_profile(payload: dict) -> dict:
    name = _safe_profile_key(payload.get("name") or "")
    cfg = load_config()
    if name not in cfg["profiles"]:
        raise ValueError(f"没有档位「{name}」")
    cfg["active"] = name
    save_config(cfg)
    return api_profiles_payload()


def api_mutate_profile(payload: dict) -> dict:
    action = (payload.get("action") or "").strip()
    cfg = load_config()
    if action == "create":
        name = _safe_profile_key(payload.get("name") or "new")
        if name in cfg["profiles"]:
            raise ValueError(f"档位「{name}」已存在")
        profile = _empty_profile(label=str(payload.get("label") or name))
        profile["REQUEST_TIMEOUT"] = str(payload.get("REQUEST_TIMEOUT") or "120")
        cfg["profiles"][name] = profile
        cfg["active"] = name
    elif action == "copy":
        src = str(payload.get("from") or cfg["active"])
        if src not in cfg["profiles"]:
            raise ValueError(f"没有档位「{src}」")
        dest = _safe_profile_key(payload.get("name") or f"{src}-copy")
        if dest in cfg["profiles"]:
            raise ValueError(f"档位「{dest}」已存在")
        copied = dict(cfg["profiles"][src])
        copied["label"] = str(payload.get("label") or f"{copied.get('label') or src} 副本")
        cfg["profiles"][dest] = copied
        cfg["active"] = dest
    elif action == "rename":
        old = str(payload.get("from") or cfg["active"])
        if old not in cfg["profiles"]:
            raise ValueError(f"没有档位「{old}」")
        new = _safe_profile_key(payload.get("name") or "")
        if new != old and new in cfg["profiles"]:
            raise ValueError(f"档位「{new}」已存在")
        profile = cfg["profiles"].pop(old)
        if payload.get("label"):
            profile["label"] = str(payload["label"])
        cfg["profiles"][new] = profile
        if cfg["active"] == old:
            cfg["active"] = new
    elif action == "delete":
        name = str(payload.get("name") or cfg["active"])
        if name not in cfg["profiles"]:
            raise ValueError(f"没有档位「{name}」")
        if len(cfg["profiles"]) <= 1:
            raise ValueError("至少保留一个档位")
        del cfg["profiles"][name]
        if cfg["active"] == name:
            cfg["active"] = next(iter(cfg["profiles"]))
    else:
        raise ValueError("未知档位操作，支持 create / copy / rename / delete")
    save_config(cfg)
    return api_profiles_payload()


def api_export_extra(payload: dict) -> dict:
    from render_diagram import export_from_stem

    stem = (payload.get("stem") or "").strip()
    kind = (payload.get("kind") or "").strip()
    if not stem:
        raise ValueError("缺少 stem")
    if kind not in ("drawio", "pptx"):
        raise ValueError("kind 只能是 drawio 或 pptx")
    path = export_from_stem(DIAGRAMS_DIR, stem, kind)
    return {
        "ok": True,
        "kind": kind,
        "path": str(path),
        "url": f"/api/files/{urllib.parse.quote(path.name)}",
        "note": "复制是图片；要改文字/颜色请下载 PPTX。" if kind == "pptx" else "",
    }


def api_copy_png(payload: dict) -> dict:
    from clipboard_png import copy_png_to_clipboard

    stem = (payload.get("stem") or "").strip()
    if not stem:
        raise ValueError("缺少 stem")
    png = DIAGRAMS_DIR / f"{stem}.png"
    copy_png_to_clipboard(png)
    return {"ok": True, "note": "已复制为图片。要改文字请导出 PPTX。"}


def _render_error_for_ui(exc) -> str:
    """界面留人话；Mermaid 语法失败时带上页面里的 Syntax error 摘要。"""
    msg = str(exc)
    detail = getattr(exc, "detail", "") or ""
    if getattr(exc, "kind", "") == "mermaid_syntax" and detail.strip():
        extra = detail.strip()
        if extra[:40] not in msg:
            msg = f"{msg}\n\n{extra[:400]}"
    return msg


def api_generate(payload: dict) -> dict:
    from archgen import generate
    from diagram_pipeline import APP_NAME, VERSION, render_diagram_outputs, resolve_style

    text = (payload.get("text") or "").strip()
    if not text:
        raise ValueError("请填写要画图的内容")
    style = payload.get("style")
    name = (payload.get("name") or "").strip() or None
    model = (payload.get("model") or "").strip() or None
    retries = int(payload.get("retries") if payload.get("retries") is not None else 1)

    env = settings_as_env()
    style_key, style_meta = resolve_style(style, env)
    _ensure_dirs()

    print(
        f"\n>>> 开始出图（{style_key}）。本机大模型写完整张图常要几分钟，"
        "下面会逐字出现；有字在涨就没卡死。\n",
        flush=True,
    )
    generate(
        text,
        "(desktop UI)",
        style_meta,
        style_key,
        model,
        str(LOG_PATH),
        env,
        quiet=False,
        retries=max(0, retries),
    )
    print("\n>>> 模型写完，正在截图导出…\n", flush=True)
    from render_diagram import RenderError

    try:
        paths = render_diagram_outputs(
            str(LOG_PATH),
            style_meta,
            diagram_name=name,
            out_dir=str(DIAGRAMS_DIR),
            quiet=True,
            with_drawio=bool(payload.get("with_drawio")),
            with_pptx=bool(payload.get("with_pptx")),
        )
    except RenderError as exc:
        raise RuntimeError(_render_error_for_ui(exc)) from exc
    if paths is None:
        raise RuntimeError("渲染失败，详情已写入 userdata/logs/archgen_output.txt")

    stem = str(paths.get("stem") or "")
    files = {k: str(v) for k, v in paths.items() if k != "stem"}
    preview = None
    if "png" in paths:
        preview = f"/api/files/{urllib.parse.quote(Path(paths['png']).name)}"
    return {
        "ok": True,
        "tool": APP_NAME,
        "version": VERSION,
        "style": style_key,
        "stem": stem,
        "files": files,
        "preview_url": preview,
        "diagrams_dir": str(DIAGRAMS_DIR),
    }


def api_render_file(payload: dict) -> dict:
    from diagram_pipeline import render_source_file, resolve_style

    rel = (payload.get("file") or payload.get("path") or "").strip()
    if not rel:
        raise ValueError("请指定 file（diagrams 下的文件名）")
    # 允许绝对路径（本机）或相对 diagrams 的文件名
    src = Path(rel)
    if not src.is_absolute():
        src = _safe_file_under(DIAGRAMS_DIR, rel)
    elif not src.exists():
        raise FileNotFoundError(str(src))

    env = settings_as_env()
    style = payload.get("style")
    style_meta = None
    if style:
        _, style_meta = resolve_style(style, env)
    name = (payload.get("name") or "").strip() or None
    from render_diagram import RenderError

    try:
        paths = render_source_file(
            str(src),
            style_meta=style_meta,
            diagram_name=name,
            out_dir=str(DIAGRAMS_DIR),
            quiet=True,
            with_drawio=bool(payload.get("with_drawio")),
            with_pptx=bool(payload.get("with_pptx")),
            log_path=str(LOG_PATH),
        )
    except RenderError as exc:
        raise RuntimeError(_render_error_for_ui(exc)) from exc
    if paths is None:
        raise RuntimeError("渲染失败，详情已写入 userdata/logs/archgen_output.txt")
    stem = str(paths.get("stem") or "")
    preview = None
    if "png" in paths:
        preview = f"/api/files/{urllib.parse.quote(Path(paths['png']).name)}"
    return {
        "ok": True,
        "stem": stem,
        "files": {k: str(v) for k, v in paths.items() if k != "stem"},
        "preview_url": preview,
    }


def api_open_folder() -> dict:
    _ensure_dirs()
    target = str(DIAGRAMS_DIR)
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", target])
    else:
        subprocess.Popen(["xdg-open", target])
    return {"ok": True, "dir": target}


class ArchGenHandler(BaseHTTPRequestHandler):
    server_version = "ArchGenDesktop/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", f"http://{HOST}")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/meta":
                return _json_response(self, 200, api_meta())
            if path == "/api/styles":
                return _json_response(self, 200, api_styles())
            if path == "/api/settings":
                return _json_response(self, 200, api_profiles_payload())
            if path == "/api/profiles":
                return _json_response(self, 200, api_profiles_payload())
            if path == "/api/models":
                return _json_response(self, 200, api_models())
            if path == "/api/history":
                return _json_response(self, 200, api_history())
            if path.startswith("/api/files/"):
                rel = urllib.parse.unquote(path[len("/api/files/") :])
                file_path = _safe_file_under(DIAGRAMS_DIR, rel)
                data = file_path.read_bytes()
                ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/tokens.css":
                # 由 design_tokens.json 动态派生（ADR 012 / T05）；不落盘，避免只读安装位置写失败
                from design_tokens import ui_css

                body = ui_css().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            # 静态资源
            return self._serve_static(path)
        except Exception as exc:  # noqa: BLE001
            return _json_response(self, 400, {"ok": False, "error": str(exc)})

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/settings":
                body = _read_json_body(self)
                settings = save_settings(body.get("settings") or body)
                return _json_response(self, 200, {"ok": True, "settings": settings})
            return _json_response(self, 404, {"ok": False, "error": "未知接口"})
        except Exception as exc:  # noqa: BLE001
            return _json_response(self, 400, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = _read_json_body(self)
            if parsed.path == "/api/probe":
                return _json_response(self, 200, api_probe(body))
            if parsed.path == "/api/generate":
                return _json_response(self, 200, api_generate(body))
            if parsed.path == "/api/render-file":
                return _json_response(self, 200, api_render_file(body))
            if parsed.path == "/api/open-folder":
                return _json_response(self, 200, api_open_folder())
            if parsed.path == "/api/profiles/switch":
                return _json_response(self, 200, api_switch_profile(body))
            if parsed.path == "/api/profiles":
                return _json_response(self, 200, api_mutate_profile(body))
            if parsed.path == "/api/export":
                return _json_response(self, 200, api_export_extra(body))
            if parsed.path == "/api/copy-png":
                return _json_response(self, 200, api_copy_png(body))
            return _json_response(self, 404, {"ok": False, "error": "未知接口"})
        except Exception as exc:  # noqa: BLE001
            return _json_response(self, 400, {"ok": False, "error": str(exc)})

    def _serve_static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve()) + os.sep):
            return _json_response(self, 403, {"ok": False, "error": "forbidden"})
        if not target.is_file():
            self.send_error(404, "Not Found")
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(open_browser: bool = True, port: Optional[int] = None) -> None:
    _bootstrap_engine()
    _ensure_dirs()
    chosen = port or find_free_port(DEFAULT_PORT)
    server = ThreadingHTTPServer((HOST, chosen), ArchGenHandler)
    url = f"http://{HOST}:{chosen}/"
    print(f"ArchGen 桌面版已启动：{url}")
    print(f"引擎目录：{ENGINE_ROOT}")
    print(f"数据目录：{USERDATA_DIR}")
    if USERDATA_DIR != ENGINE_ROOT / "userdata":
        print("（包内目录不可写或被 ARCHGEN_USERDATA 覆盖，已回退到系统用户数据目录）")
    print(f"产出目录：{DIAGRAMS_DIR}")
    print("按 Control+C 停止。")

    if open_browser:
        def _open() -> None:
            time.sleep(0.6)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ArchGen 本地绿色版")
    parser.add_argument("--port", type=int, default=None, help="端口（默认 8765，占用则递增）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    main(open_browser=not args.no_browser, port=args.port)
