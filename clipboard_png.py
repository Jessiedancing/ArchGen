"""把 PNG 作为图片内容写入系统剪贴板（T06 / T13）。

Windows 禁止 `Set-Clipboard -Path`：那复制的是文件引用，粘进 PPT 会变成图标。
必须用 `Clipboard::SetImage`。PowerShell 调用带 `-NoProfile -ExecutionPolicy Bypass`。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


def macos_osascript_args(path: Path) -> list[str]:
    posix = str(Path(path).resolve())
    script = (
        "set the clipboard to (read (POSIX file "
        f"{json.dumps(posix)}) as «class PNGf»)"
    )
    return ["osascript", "-e", script]


def windows_powershell_args(path: Path) -> list[str]:
    posix = str(Path(path).resolve())
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        f"$img = [System.Drawing.Image]::FromFile({json.dumps(posix)}); "
        "[System.Windows.Forms.Clipboard]::SetImage($img); "
        "$img.Dispose()"
    )
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        ps,
    ]


def linux_xclip_args(path: Path) -> list[str]:
    return ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", str(Path(path).resolve())]


def copy_png_to_clipboard(path: Path, platform: Optional[str] = None) -> None:
    """按平台分派。platform 可注入，便于单测而不真写剪贴板。"""
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"找不到 PNG：{src}")
    plat = platform if platform is not None else sys.platform
    if plat == "darwin":
        args = macos_osascript_args(src)
    elif plat.startswith("win"):
        args = windows_powershell_args(src)
        if "Set-Clipboard" in " ".join(args) and "-Path" in " ".join(args):
            raise RuntimeError("内部错误：Windows 剪贴板不能用 Set-Clipboard -Path")
    else:
        args = linux_xclip_args(src)
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"本机缺少剪贴板命令：{args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"写入剪贴板失败：{detail or exc}") from exc
