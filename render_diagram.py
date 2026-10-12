"""从模型输出导出图表：支持 Mermaid 与分层色块架构 HTML。"""

from __future__ import annotations

import datetime
import html
import json
import re
from pathlib import Path
from typing import Any, Optional


APP_LABEL = "ArchGen"
# 内置资源锚定到代码目录（ADR 014.1 / T14.1）：无论调用方 cwd 在哪都能找到
ENGINE_ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ENGINE_ROOT / "vendor"
MERMAID_RUNTIME_SRC = VENDOR_DIR / "mermaid.min.js"
# 锁定随包分发的 Mermaid 运行时版本（T02 / ADR 012）；升级时同步替换 vendor/ 文件
MERMAID_RUNTIME_VERSION = "10.9.1"
_MERMAID_RUNTIME_CACHE: Optional[str] = None
# 用户数据（输出目录）默认相对调用方 cwd，符合用户预期（ADR 008），保持相对路径
DIAGRAMS_DIR = Path("diagrams")
# 每次 skill 出图固定交付（额外格式如 json 可并存）
STANDARD_OUTPUTS = ("png", "html", "md", "mmd")

KIND_PLAYWRIGHT = "playwright_missing"
KIND_BROWSER = "browser_unavailable"
KIND_MERMAID = "mermaid_syntax"
KIND_TIMEOUT = "timeout"
KIND_OTHER = "other"
MERMAID_USER_MESSAGE = (
    "Mermaid 语法错误，PNG 未导出。"
    "流程图源码已写在产出文件夹的 .mmd，可点「打开文件夹」查看。"
    "本机小模型经常写出不合法的流程图，建议改选「分层色块架构图」再生成。"
)
CHROME_DOWNLOAD = "https://www.google.com/chrome/"
EDGE_DOWNLOAD = "https://www.microsoft.com/edge"


class RenderError(RuntimeError):
    """分类后的渲染失败（A-03 / A-04）。kind 供日志与 UI 分支。"""

    def __init__(self, kind: str, message: str, detail: str = ""):
        super().__init__(message)
        self.kind = kind
        self.detail = detail or ""


def browser_unavailable_user_message() -> str:
    """界面用人话；三级回退全文只进 RenderError.detail / 日志（B-02）。"""
    return (
        "未检测到可用的 Chrome 或 Edge，请安装任一后重试。\n"
        f"Chrome：{CHROME_DOWNLOAD}\n"
        f"Edge：{EDGE_DOWNLOAD}\n"
        "不要在 Cursor 里启动本程序：沙箱会强杀 Chrome，看起来像渲染失败。请用系统「终端」打开。"
    )


def browser_unavailable_message(channel_errors: list[str]) -> str:
    """兼容旧调用：人话 + 通道明细。新代码请分别用 user_message 与 detail。"""
    lines = [browser_unavailable_user_message(), "各通道原因："]
    lines.extend(channel_errors or ["(无明细)"])
    return "\n".join(lines)


def classify_render_error(exc: BaseException) -> RenderError:
    if isinstance(exc, RenderError):
        return exc
    text = str(exc)
    name = type(exc).__name__
    if isinstance(exc, ImportError) or "No module named 'playwright'" in text or "缺少 playwright" in text:
        return RenderError(
            KIND_PLAYWRIGHT,
            "未安装 Playwright（Python 包）。开发环境请执行：python3 -m pip install playwright\n"
            "绿色包用户请安装 Chrome 或 Edge 后重试，不必装 Python。",
            text,
        )
    if "Syntax error" in text or "Mermaid 渲染报语法错误" in text or "Mermaid 语法错误" in text:
        return RenderError(KIND_MERMAID, MERMAID_USER_MESSAGE, text)
    if name in {"TimeoutError", "Timeout"} or "Timeout" in name or "timeout" in text.lower():
        return RenderError(KIND_TIMEOUT, "渲染超时：页面未在时限内完成绘制。", text)
    if "无法启动浏览器" in text or "未检测到可用的 Chrome" in text:
        return RenderError(KIND_BROWSER, browser_unavailable_user_message(), text)
    return RenderError(KIND_OTHER, text, text)


def log_render_failure(log_path: str | Path, err: RenderError) -> None:
    """把渲染异常写入与模型输出同一份日志（A-03），用户按提示能看到原因。"""
    from llm_gateway import prepend_record

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = (
        f"\n{'=' * 60}\n"
        f"[时间] {stamp}\n"
        f"[渲染失败] kind={err.kind}\n"
        f"{err}\n"
    )
    if err.detail and err.detail.strip() and err.detail.strip() not in str(err):
        body += f"{'-' * 60}\n[detail]\n{err.detail.rstrip()}\n"
    prepend_record(str(log_path), body)


# 文件名：{名称}_{YYYYMMDD}_V{n}
STEM_SUFFIX_RE = re.compile(r"_(?P<date>\d{8})_V(?P<ver>\d+)$")
ILLEGAL_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')

MERMAID_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<title>{title}</title>
<!-- Mermaid 运行时内联随包（vendor/），断网 / 单文件分享均可渲染，不依赖 CDN（T02 / ADR 012） -->
<script>{runtime_js}</script>
<script>
  mermaid.initialize({config_json});
</script>
<style>
  html, body {{ margin: 0; background: #fff; font-family: {font_family}; }}
  /* T12：按内容收缩，去掉 min-width:1200px 造成的左右大白边 */
  .page {{ padding: 24px 28px 28px; width: fit-content; max-width: none; box-sizing: border-box; }}
  h1 {{ margin: 0 0 8px; font-size: 22px; text-align: center; }}
  .meta {{ margin: 0 0 16px; text-align: center; color: #6b7280; font-size: 12px; }}
  .mermaid {{ display: inline-block; }}
  .mermaid svg .node rect {{ rx: 8; ry: 8; }}
</style>
</head>
<body>
  <div class="page" id="capture">
    <h1>{title}</h1>
    <p class="meta">{meta}</p>
    <pre class="mermaid">
{mermaid}
    </pre>
  </div>
</body>
</html>
"""

# 每层一套配色：边框 / 层底色 / 标题条渐变 / 文字色。
# 单一来源为 design_tokens.json（ADR 012 / T05）；加载失败回退内置值，保证不崩。
_FALLBACK_LAYER_THEMES = [
    ("#6ea8dc", "#f2f8ff", "#cfe4fb", "#e9f3fe", "#1a4d8f"),  # blue
    ("#77bd76", "#f3fbf3", "#d5f0d2", "#eaf8e8", "#22662a"),  # green
    ("#6fa8d8", "#f2f8ff", "#cbe2f7", "#e7f2fc", "#17508c"),  # blue
    ("#6ab5c4", "#f1fbfc", "#cbeaf0", "#e7f7fa", "#125e6b"),  # cyan
    ("#a98cd8", "#faf6ff", "#e4d9f6", "#f2ecfb", "#553a94"),  # purple
    ("#e0a86a", "#fff8f0", "#fbe3c8", "#fdf1e2", "#8a5116"),  # orange
]
_FALLBACK_EXTERNAL_THEME = ("#94a3b8", "#fafafa", "#e8ecf1", "#f3f5f8", "#41546b")

try:
    from design_tokens import external_layer_theme as _ext_theme
    from design_tokens import layer_themes as _layer_themes

    LAYER_THEMES = _layer_themes() or _FALLBACK_LAYER_THEMES
    EXTERNAL_THEME = _ext_theme()
except Exception:  # noqa: BLE001 - token 缺失时不影响出图
    LAYER_THEMES = _FALLBACK_LAYER_THEMES
    EXTERNAL_THEME = _FALLBACK_EXTERNAL_THEME


def extract_mermaid(text: str) -> Optional[str]:
    match = re.search(r"```mermaid\s*\n(.*?)```", text, re.S | re.I)
    if not match:
        return None
    return match.group(1).strip()


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """从模型输出中提取 JSON 对象。先剥离 reasoning / <think>，避免花括号污染（T07）。"""
    try:
        from llm_gateway import strip_reasoning

        cleaned = strip_reasoning(text)
    except Exception:  # noqa: BLE001
        cleaned = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1).strip()
    # 截取第一个 { 到最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_latest_assistant(log_text: str) -> str:
    marker = "[assistant]\n"
    idx = log_text.find(marker)
    if idx < 0:
        return log_text
    rest = log_text[idx + len(marker) :]
    sep = "\n" + ("=" * 60)
    end = rest.find(sep)
    if end >= 0:
        rest = rest[:end]
    return rest.strip()


def sanitize_diagram_name(name: str, fallback: str = "未命名图表") -> str:
    """图名清洗为可用文件名片段（保留中文）。"""
    text = str(name or "").strip()
    text = text.replace("·", "_").replace("—", "-").replace("–", "-")
    text = ILLEGAL_NAME_CHARS.sub("_", text)
    text = re.sub(r"\s+", "", text)  # 中文名去掉空格更紧凑
    text = re.sub(r"_+", "_", text).strip("._-")
    if not text:
        text = fallback
    return text[:48]


def today_stamp(day: Optional[datetime.date] = None) -> str:
    return (day or datetime.date.today()).strftime("%Y%m%d")


# 图种通名：不能当文件名（T12）。内容里的 %% 图名 / JSON title 优先。
GENERIC_DIAGRAM_NAMES = {
    "未命名图表",
    "技术架构图",
    "技术图表",
    "架构图",
    "分层色块架构图",
    "流程图",
    "时序图",
    "数据流图",
    "部署拓扑图",
    "状态机图",
    "实体关系图",
    "技术解析图",
}


def derive_diagram_name(
    *,
    title: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
    mermaid: Optional[str] = None,
    name_hint: Optional[str] = None,
) -> str:
    """内容主题优先于图种通名：JSON title / %% 图名 > style title / name_hint。"""
    ordered: list[str] = []
    if data and data.get("title"):
        ordered.append(str(data["title"]))
    if mermaid:
        comment = re.search(r"^\s*%%\s+(?!\{)(.+)$", mermaid, re.M)
        if comment:
            ordered.append(comment.group(1).strip())
    if title:
        ordered.append(str(title))
    if name_hint:
        ordered.append(str(name_hint))
    fallback = ""
    for raw in ordered:
        cleaned = sanitize_diagram_name(raw)
        if not cleaned:
            continue
        if not fallback:
            fallback = cleaned
        if cleaned not in GENERIC_DIAGRAM_NAMES:
            return cleaned
    return fallback or sanitize_diagram_name("未命名图表")


def next_version_number(
    name: str,
    date_stamp: str,
    diagrams_dir: Path = DIAGRAMS_DIR,
) -> int:
    """扫描同名同日已有文件，返回下一版本号（从 1 起）。"""
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    max_ver = 0
    for path in diagrams_dir.iterdir():
        if not path.is_file():
            continue
        m = STEM_SUFFIX_RE.search(path.stem)
        if not m:
            continue
        if m.group("date") != date_stamp:
            continue
        file_name = path.stem[: m.start()]
        if file_name == name:
            max_ver = max(max_ver, int(m.group("ver")))
    return max_ver + 1


def allocate_versioned_stem(
    name: str,
    diagrams_dir: Path = DIAGRAMS_DIR,
    day: Optional[datetime.date] = None,
    version: Optional[int] = None,
) -> str:
    """生成 {名称}_{YYYYMMDD}_V{n}。"""
    safe_name = sanitize_diagram_name(name)
    date_stamp = today_stamp(day)
    ver = version or next_version_number(safe_name, date_stamp, diagrams_dir)
    return f"{safe_name}_{date_stamp}_V{ver}"


def _safe_mermaid_id(prefix: str, raw: str, used: set[str]) -> str:
    base = re.sub(r"[^0-9A-Za-z_]", "", re.sub(r"\s+", "_", str(raw)))
    candidate = (f"{prefix}_{base}" if base else prefix)[:48]
    if candidate not in used:
        used.add(candidate)
        return candidate
    i = 2
    while f"{candidate}_{i}" in used:
        i += 1
    final = f"{candidate}_{i}"
    used.add(final)
    return final


def _escape_mermaid_label(text: str) -> str:
    return str(text).replace('"', "'").replace("\n", " ")


def layered_json_to_mermaid(data: dict[str, Any]) -> str:
    """将分层架构 JSON 转为可编辑的 Mermaid flowchart（与 HTML 截图同源）。"""
    title = _escape_mermaid_label(data.get("title") or "技术架构图")
    layers = data.get("layers") or []
    external = data.get("external") or []
    used: set[str] = set()
    layer_ids: list[str] = []
    lines = ["flowchart TB", f"  %% {title}"]
    for i, layer in enumerate(layers):
        lname = _escape_mermaid_label(layer.get("name") or f"层级{i+1}")
        lid = _safe_mermaid_id(f"L{i}", lname, used)
        layer_ids.append(lid)
        lines.append(f'  subgraph {lid}["{lname}"]')
        for j, mod in enumerate(layer.get("modules") or []):
            mt = _escape_mermaid_label(mod.get("title") or f"模块{j+1}")
            items = mod.get("items") or []
            if isinstance(items, str):
                items = [items]
            detail = "、".join(_escape_mermaid_label(x) for x in items[:6])
            label = f"{mt}<br/>{detail}" if detail else mt
            mid = _safe_mermaid_id(f"M{i}{j}", mt, used)
            lines.append(f'    {mid}["{label}"]')
        lines.append("  end")
    for a, b in zip(layer_ids, layer_ids[1:]):
        lines.append(f"  {a} --> {b}")
    if external:
        eid = _safe_mermaid_id("EXT", "外部对接", used)
        lines.append(f'  subgraph {eid}["外部对接系统"]')
        for k, ext in enumerate(external):
            et = _escape_mermaid_label(ext.get("title") or f"外部{k+1}")
            ed = _escape_mermaid_label(ext.get("desc") or "")
            label = f"{et}<br/>{ed}" if ed else et
            xid = _safe_mermaid_id(f"X{k}", et, used)
            lines.append(f'    {xid}["{label}"]')
        lines.append("  end")
        if layer_ids:
            lines.append(f"  {layer_ids[0]} -.-> {eid}")
    return "\n".join(lines) + "\n"


def build_package_md(
    *,
    title: str,
    subtitle: str,
    mermaid: str,
    stem: str,
    extra_note: str = "",
) -> str:
    """固定交付物说明：PNG / HTML / MD / Mermaid 一键可得。"""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    note = f"\n{extra_note.strip()}\n" if extra_note.strip() else ""
    return (
        f"# {title}\n\n"
        f"{subtitle}\n\n"
        f"> 自动导出 · {stamp} · stem=`{stem}`\n"
        f"{note}\n"
        "## 交付文件（同目录）\n\n"
        f"- 高清截图：`{stem}.png`\n"
        f"- 可交互 HTML：`{stem}.html`\n"
        f"- 本文档：`{stem}.md`\n"
        f"- Mermaid 源码：`{stem}.mmd`\n\n"
        "## 用 draw.io 打开（兜底，T04）\n\n"
        "1. 打开 [diagrams.net](https://app.diagrams.net/) 或桌面版 draw.io\n"
        "2. Arrange → Insert → Advanced → Mermaid\n"
        f"3. 粘贴同目录 `{stem}.mmd` 的全部内容后插入\n"
        "4. 插入后可改节点文字和颜色\n\n"
        f"若已用 `--with-drawio` / 桌面「导出 draw.io」生成 `{stem}.drawio`，"
        "直接用 draw.io 打开即可（原生形状，连线跟随节点）。"
        "复制到 PPT 的是图片；要改文字请导出 `.pptx`。\n\n"
        "## Mermaid\n\n"
        "```mermaid\n"
        f"{mermaid.strip()}\n"
        "```\n"
    )


def mermaid_runtime_js() -> str:
    """读取随包 Mermaid 运行时源码（进程内缓存），供内联进 HTML。

    内联而非拷贝到输出目录旁：输出文件夹只留图表本身（png/html/md/mmd），
    用户「打开文件夹」看到的是干净目录；`.html` 也自包含，单文件分享/离线打开都能渲。
    """
    global _MERMAID_RUNTIME_CACHE
    if _MERMAID_RUNTIME_CACHE is not None:
        return _MERMAID_RUNTIME_CACHE
    if not MERMAID_RUNTIME_SRC.exists():
        raise RuntimeError(
            f"缺少 Mermaid 运行时：{MERMAID_RUNTIME_SRC}。"
            "请确认 vendor/mermaid.min.js 随包分发（T02 / ADR 012）。"
        )
    js = MERMAID_RUNTIME_SRC.read_text(encoding="utf-8")
    # 防御：内联脚本里若出现 </script 会截断文档（当前构建未命中，仍做保护）
    js = re.sub(r"</script", r"<\\/script", js, flags=re.I)
    _MERMAID_RUNTIME_CACHE = js
    return js


def _mermaid_init_json() -> tuple[str, str]:
    """theme/themeVariables/flowchart 全部来自 design_tokens（T01 接上生产者）。"""
    try:
        from design_tokens import mermaid_config

        cfg = mermaid_config()
    except Exception:  # noqa: BLE001
        cfg = {
            "theme": "base",
            "themeVariables": {
                "fontFamily": '"Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
            },
            "flowchart": {},
        }
    variables = dict(cfg.get("themeVariables") or {})
    flow = dict(cfg.get("flowchart") or {})
    flow.setdefault("htmlLabels", True)
    flow.setdefault("curve", "basis")
    payload = {
        "startOnLoad": True,
        "theme": cfg.get("theme") or "base",
        "securityLevel": "loose",
        "fontFamily": variables.get("fontFamily"),
        "themeVariables": variables,
        "flowchart": flow,
    }
    font_family = variables.get("fontFamily") or payload["fontFamily"] or "sans-serif"
    return json.dumps(payload, ensure_ascii=False), font_family


def build_mermaid_html(mermaid: str, title: str = "架构图") -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    safe = mermaid.replace("</", "<\\/")
    config_json, font_family = _mermaid_init_json()
    return MERMAID_HTML_TEMPLATE.format(
        title=html.escape(title),
        meta=f"自动渲染 · {stamp}",
        mermaid=safe,
        runtime_js=mermaid_runtime_js(),
        config_json=config_json,
        font_family=font_family,
    )


def _page_layout() -> dict[str, float]:
    """版式数值一律来自 design_tokens.json 的 page（T05 / T14.6），缺项用兜底。"""
    defaults = {
        "width": 1180.0,
        "padding": 38.0,
        "chip_font_px": 12.5,
        "chip_pad_px": 18.0,
        "layer_border_px": 3.0,
        "groups_pad_x": 28.0,
        "group_gap": 12.0,
        "group_box_inset": 22.0,
        "chip_gap": 8.0,
        "max_chip_cols": 5.0,
    }
    try:
        from design_tokens import page_config

        raw = page_config() or {}
    except Exception:  # noqa: BLE001
        raw = {}
    out = dict(defaults)
    for key in defaults:
        if raw.get(key) is None:
            continue
        try:
            out[key] = float(raw[key])
        except (TypeError, ValueError):
            pass
    return out


# 兼容旧引用；运行时请优先走 _page_layout()
PAGE_WIDTH = int(_page_layout()["width"])
PAGE_PADDING = int(_page_layout()["padding"])
CHIP_FONT_PX = _page_layout()["chip_font_px"]


def _pick_chip_columns(count: int, avail: float, need: float, gap: float, max_cols: int) -> int:
    """行数最少的前提下取最小列数，避免 3+1 落单行（ADR 007）。"""
    if count <= 1:
        return 1
    fit = 1
    for cols in range(1, min(count, max_cols) + 1):
        if (avail - gap * (cols - 1)) / cols >= need:
            fit = cols
    rows = -(-count // fit)
    for cols in range(1, fit + 1):
        if -(-count // cols) == rows:
            return cols
    return fit


def _chip_columns(group_count: int, items: list[str], boxed: bool = True) -> int:
    """无浏览器时的字宽估算兜底。截图前由实测脚本改列数（T14.6）。"""
    count = len(items)
    if count <= 1:
        return 1
    layout = _page_layout()
    content = layout["width"] - layout["padding"] * 2 - layout["layer_border_px"]
    avail = (
        content - layout["groups_pad_x"] - layout["group_gap"] * (group_count - 1)
    ) / max(group_count, 1)
    if boxed:
        avail -= layout["group_box_inset"]
    longest = max(len(str(x)) for x in items)
    need = longest * layout["chip_font_px"] + layout["chip_pad_px"]
    return _pick_chip_columns(
        count, avail, need, layout["chip_gap"], int(layout["max_chip_cols"])
    )


# 截图前 / 打开 HTML 时用浏览器实测字宽改列数（T14.6，跨平台首要隐患）
CHIP_REFLOW_JS = """
async function __archgenReflowChips() {
  if (document.fonts && document.fonts.ready) {
    try { await document.fonts.ready; } catch (e) { /* 字体就绪失败仍用当前字体测 */ }
  }
  function pickCols(count, avail, need, gap) {
    if (count <= 1) return 1;
    var fit = 1;
    var maxCols = Math.min(count, 5);
    for (var cols = 1; cols <= maxCols; cols++) {
      if ((avail - gap * (cols - 1)) / cols >= need) fit = cols;
    }
    var rows = Math.ceil(count / fit);
    for (var cols = 1; cols <= fit; cols++) {
      if (Math.ceil(count / cols) === rows) return cols;
    }
    return fit;
  }
  function measureNeed(chip) {
    var cs = getComputedStyle(chip);
    var canvas = document.createElement("canvas");
    var ctx = canvas.getContext("2d");
    ctx.font = cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
    var longest = 0;
    var strong = chip.querySelector("strong");
    var span = chip.querySelector("span");
    var texts = (strong || span)
      ? [(strong && strong.textContent) || "", (span && span.textContent) || ""]
      : [chip.textContent || ""];
    texts.forEach(function (t) {
      var w = ctx.measureText(String(t).trim()).width;
      if (w > longest) longest = w;
    });
    var pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    var border = (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
    return longest + pad + border;
  }
  document.querySelectorAll(".chips").forEach(function (grid) {
    var chips = Array.prototype.slice.call(grid.querySelectorAll(":scope > .chip"));
    if (!chips.length) return;
    var gap = parseFloat(getComputedStyle(grid).columnGap || getComputedStyle(grid).gap) || 8;
    var avail = grid.clientWidth;
    var need = 0;
    chips.forEach(function (chip) {
      var n = measureNeed(chip);
      if (n > need) need = n;
    });
    var cols = pickCols(chips.length, avail, need, gap);
    grid.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";
  });
  document.documentElement.setAttribute("data-chip-reflow", "done");
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", function () { __archgenReflowChips(); });
} else {
  __archgenReflowChips();
}
"""


def _normalize_items(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if not raw:
        return []
    return [str(x) for x in raw]


def _chips_html(items: list[str], cols: int) -> str:
    chips = "".join(f'<div class="chip">{html.escape(x)}</div>' for x in items)
    return (
        f'<div class="chips" style="grid-template-columns:repeat({cols},minmax(0,1fr))">'
        f"{chips}</div>"
    )


def build_layered_html(data: dict[str, Any]) -> str:
    """生成产品级分层架构 HTML：层标题条 + 分组框 + 独立能力块 + 层间箭头。"""
    title = html.escape(str(data.get("title") or "技术架构图"))
    subtitle = html.escape(str(data.get("subtitle") or ""))
    layers = data.get("layers") or []
    external = data.get("external") or []

    blocks: list[str] = []
    for i, layer in enumerate(layers):
        border, body_bg, tb1, tb2, fg = LAYER_THEMES[i % len(LAYER_THEMES)]
        name = html.escape(str(layer.get("name") or f"层级{i+1}"))
        modules = [m for m in (layer.get("modules") or []) if m]

        has_title = any(str(m.get("title") or "").strip() for m in modules)
        if has_title:
            groups: list[str] = []
            group_count = min(max(len(modules), 1), 4)
            for mod in modules:
                mt = str(mod.get("title") or "").strip()
                items = _normalize_items(mod.get("items"))
                cols = _chip_columns(group_count, items)
                body = _chips_html(items, cols) if items else ""
                head = f"<h3>{html.escape(mt)}</h3>" if mt else ""
                groups.append(f'<div class="group">{head}{body}</div>')
            inner = (
                f'<div class="groups" style="grid-template-columns:repeat({group_count},minmax(0,1fr))">'
                + "".join(groups)
                + "</div>"
            )
        else:
            # 该层只是并列入口/能力，不需要分组框，直接铺能力块
            flat: list[str] = []
            for mod in modules:
                flat.extend(_normalize_items(mod.get("items")))
            cols = _chip_columns(1, flat, boxed=False)
            inner = f'<div class="bare">{_chips_html(flat, cols)}</div>'

        style = f"--bd:{border};--body:{body_bg};--tb1:{tb1};--tb2:{tb2};--fg:{fg}"
        blocks.append(
            f'<section class="layer" style="{style}">'
            f'<div class="layer-title">{name}</div>'
            f"{inner}</section>"
        )
        if i < len(layers) - 1:
            blocks.append(f'<div class="arrow" style="--bd:{border}"></div>')

    ext_html = ""
    if external:
        chips = []
        for ext in external:
            et = html.escape(str(ext.get("title") or "外部系统"))
            ed = html.escape(str(ext.get("desc") or ""))
            desc = f'<span>{ed}</span>' if ed else ""
            chips.append(f'<div class="chip ext"><strong>{et}</strong>{desc}</div>')
        cols = min(max(len(external), 1), 4)
        ebd, ebody, etb1, etb2, efg = EXTERNAL_THEME
        ext_html = (
            f'<div class="arrow arrow-dashed" style="--bd:{ebd}"></div>'
            f'<section class="layer layer-ext" style="--bd:{ebd};--body:{ebody};'
            f'--tb1:{etb1};--tb2:{etb2};--fg:{efg}">'
            '<div class="layer-title">外部对接系统</div>'
            f'<div class="bare"><div class="chips" '
            f'style="grid-template-columns:repeat({cols},minmax(0,1fr))">'
            + "".join(chips)
            + "</div></div></section>"
        )

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sub_html = f'<p class="sub">{subtitle}</p>' if subtitle else ""
    layout = _page_layout()
    page_w = int(layout["width"])
    page_pad = int(layout["padding"])
    try:
        from design_tokens import font_stack

        ui_font = font_stack("ui")
    except Exception:  # noqa: BLE001
        ui_font = '"Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #eef1f5; color: #1f2937;
    font-family: {ui_font};
    -webkit-font-smoothing: antialiased;
  }}
  .page {{ width: {page_w}px; margin: 0 auto; padding: 34px {page_pad}px 34px; background: #fff; }}
  h1 {{ margin: 0 0 6px; font-size: 24px; text-align: center; letter-spacing: .5px; }}
  .sub {{ margin: 0 0 22px; text-align: center; color: #7b8794; font-size: 13px; }}
  .stack {{ display: flex; flex-direction: column; }}

  .layer {{
    border: 1.5px solid var(--bd); border-radius: 8px;
    background: var(--body); overflow: hidden;
  }}
  .layer-title {{
    text-align: center; font-size: 15px; font-weight: 700; color: var(--fg);
    padding: 8px 10px; letter-spacing: .5px;
    background: linear-gradient(180deg, var(--tb1) 0%, var(--tb2) 100%);
    border-bottom: 1px solid var(--bd);
  }}
  .groups {{ display: grid; gap: 12px; padding: 12px 14px 14px; align-items: stretch; }}
  .bare {{ padding: 12px 14px 14px; }}
  .group {{
    border: 1px dashed var(--bd); border-radius: 6px;
    background: rgba(255,255,255,.6); padding: 10px 10px 12px;
  }}
  .group h3 {{
    margin: 0 0 10px; font-size: 13.5px; font-weight: 600;
    text-align: center; color: var(--fg);
  }}
  .chips {{ display: grid; gap: 8px; }}
  .chip {{
    background: #fff; border: 1px solid var(--bd); border-radius: 4px;
    padding: 7px 6px; font-size: 12.5px; line-height: 1.35;
    text-align: center; color: #33445c; min-height: 32px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
  }}
  .chip.ext {{ padding: 8px 8px; }}
  .chip.ext strong {{ font-size: 12.5px; font-weight: 600; }}
  .chip.ext span {{ margin-top: 3px; font-size: 11.5px; color: #7b8794; }}

  .arrow {{ height: 26px; position: relative; }}
  .arrow::before {{
    content: ""; position: absolute; left: 50%; top: 2px;
    width: 1.5px; height: 16px; background: var(--bd); transform: translateX(-50%);
  }}
  .arrow::after {{
    content: ""; position: absolute; left: 50%; top: 16px;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 7px solid var(--bd); transform: translateX(-50%);
  }}
  .arrow-dashed::before {{
    background: repeating-linear-gradient(180deg, var(--bd) 0 4px, transparent 4px 8px);
  }}
  .layer-ext .chip {{ border-style: dashed; }}

  .meta {{ margin: 20px 0 0; text-align: center; color: #a3adb9; font-size: 11.5px; }}
</style>
</head>
<body>
  <div class="page" id="capture">
    <h1>{title}</h1>
    {sub_html}
    <div class="stack">
      {''.join(blocks)}
      {ext_html}
    </div>
    <p class="meta">{APP_LABEL} 自动渲染 · {stamp}</p>
  </div>
<script>
{CHIP_REFLOW_JS}
</script>
</body>
</html>
"""


def _launch_browser(p):
    browser = None
    errors: list[str] = []
    for label, kwargs in (
        ("chromium", {}),
        ("chrome", {"channel": "chrome"}),
        ("msedge", {"channel": "msedge"}),
    ):
        try:
            browser = p.chromium.launch(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    if browser is None:
        raise RenderError(KIND_BROWSER, browser_unavailable_user_message(), "\n".join(errors))
    return browser


def screenshot_html(html_path: Path, png_path: Path, scale: float = 3.0) -> Optional[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError(
            KIND_PLAYWRIGHT,
            "未安装 Playwright（Python 包）。开发环境请执行：python3 -m pip install playwright\n"
            "绿色包用户请安装 Chrome 或 Edge 后重试，不必装 Python。",
            str(exc),
        ) from exc

    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page(
            device_scale_factor=scale,
            viewport={"width": 1800, "height": 1400},
        )
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        # mermaid 页等 svg；分层 HTML 等 #capture
        try:
            page.wait_for_selector("svg", timeout=8000)
        except Exception:  # noqa: BLE001
            try:
                page.wait_for_selector("#capture", timeout=10000)
            except Exception as exc:  # noqa: BLE001
                browser.close()
                raise RenderError(
                    KIND_TIMEOUT,
                    "渲染超时：等待图表绘制超时。",
                    str(exc),
                ) from exc

        # Mermaid 解析失败时会渲染一个错误图，此处提前拦截，避免导出一张“报错图”
        try:
            body_text = page.inner_text("body", timeout=2000)
        except Exception:  # noqa: BLE001
            body_text = ""
        if "Syntax error in text" in body_text or "mermaid version" in body_text.lower():
            browser.close()
            raise RenderError(KIND_MERMAID, MERMAID_USER_MESSAGE, body_text[:500])

        # 架构图：用当前机器字体实测字宽再定列数，然后把列数写回 HTML（T14.6）
        if page.locator(".chips").count() > 0:
            page.evaluate(
                "async () => { if (window.__archgenReflowChips) await window.__archgenReflowChips(); }"
            )
            page.wait_for_function(
                "document.documentElement.getAttribute('data-chip-reflow') === 'done'",
                timeout=5000,
            )
            html_path.write_text(page.content(), encoding="utf-8")

        # GraphIR：与 PNG 同一坐标系抽节点（T00）。截图前抽，reflow 后的 DOM 更准。
        ir = None
        try:
            from graph_ir import extract_ir_from_page, write_ir

            ir = extract_ir_from_page(page, title_fallback=html_path.stem)
            if ir and ir.get("nodes"):
                write_ir(html_path.with_name(f"{html_path.stem}.ir.json"), ir)
        except Exception:  # noqa: BLE001
            ir = None

        page.locator("#capture").screenshot(path=str(png_path), type="png")
        browser.close()
        return ir


def extract_ir_via_browser(html_path: Path, title_fallback: str = "") -> Optional[dict]:
    """单独打开 HTML 抽 GraphIR（无 PNG 时的兜底，T00）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    from graph_ir import extract_ir_from_page

    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = browser.new_page(viewport={"width": 1800, "height": 1400})
        page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
        try:
            page.wait_for_selector("svg, #capture", timeout=8000)
        except Exception:  # noqa: BLE001
            browser.close()
            return None
        if page.locator(".chips").count() > 0:
            try:
                page.evaluate(
                    "async () => { if (window.__archgenReflowChips) await window.__archgenReflowChips(); }"
                )
            except Exception:  # noqa: BLE001
                pass
        ir = extract_ir_from_page(page, title_fallback=title_fallback or Path(html_path).stem)
        browser.close()
        return ir


def export_extras(
    ir: dict,
    stem: str,
    diagrams_dir: Path,
    *,
    with_drawio: bool = False,
    with_pptx: bool = False,
    raise_on_error: bool = False,
) -> dict[str, Path]:
    """按需从 GraphIR 出 drawio / pptx（ADR 011：不进四件套必出）。"""
    extras: dict[str, Path] = {}
    if with_drawio:
        try:
            from ir_to_drawio import write_drawio

            extras["drawio"] = write_drawio(ir, Path(diagrams_dir) / f"{stem}.drawio")
        except Exception as exc:  # noqa: BLE001
            if raise_on_error:
                raise
            print(f"[drawio] 导出失败：{exc}", file=__import__("sys").stderr)
    if with_pptx:
        try:
            from ir_to_pptx import write_pptx

            extras["pptx"] = write_pptx(ir, Path(diagrams_dir) / f"{stem}.pptx")
        except Exception as exc:  # noqa: BLE001
            if raise_on_error:
                raise
            print(f"[pptx] 导出失败：{exc}", file=__import__("sys").stderr)
    return extras


def attach_graph_ir_and_extras(
    paths: dict,
    stem: str,
    diagrams_dir: Path,
    *,
    ir: Optional[dict] = None,
    layered_data: Optional[dict] = None,
    with_drawio: bool = False,
    with_pptx: bool = False,
) -> dict:
    """写入 .ir.json，并按需导出 drawio/pptx。"""
    from graph_ir import ir_from_outputs, layered_json_to_ir, write_ir

    if ir is None or not ir.get("nodes"):
        if layered_data:
            ir = layered_json_to_ir(layered_data)
        else:
            try:
                ir = ir_from_outputs(Path(diagrams_dir), stem)
            except FileNotFoundError:
                ir = None
    if ir and ir.get("nodes"):
        ir_path = Path(diagrams_dir) / f"{stem}.ir.json"
        write_ir(ir_path, ir)
        paths["ir"] = ir_path
        paths.update(
            export_extras(
                ir,
                stem,
                Path(diagrams_dir),
                with_drawio=with_drawio,
                with_pptx=with_pptx,
            )
        )
    elif with_drawio or with_pptx:
        print("[导出] 无法生成 GraphIR，已跳过 drawio/pptx", file=__import__("sys").stderr)
    return paths


def export_from_stem(diagrams_dir: Path, stem: str, kind: str) -> Path:
    """从已落盘产物按需导出 drawio / pptx（桌面按钮 / MCP）。"""
    from graph_ir import ir_from_outputs

    ir = ir_from_outputs(Path(diagrams_dir), stem)
    extras = export_extras(
        ir,
        stem,
        Path(diagrams_dir),
        with_drawio=(kind == "drawio"),
        with_pptx=(kind == "pptx"),
        raise_on_error=True,
    )
    if kind not in extras:
        raise RuntimeError(f"未能导出 {kind}")
    return extras[kind]


def render_mermaid_files(
    mermaid: str,
    stem: str = "skill_diagram",
    title: str = "技术架构图",
    diagrams_dir: Path = DIAGRAMS_DIR,
    scale: float = 3.0,
    subtitle: str = "流程图 / 时序图",
    with_drawio: bool = False,
    with_pptx: bool = False,
) -> dict[str, Path]:
    """固定导出：png + html + md + mmd。"""
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    mmd_path = diagrams_dir / f"{stem}.mmd"
    html_path = diagrams_dir / f"{stem}.html"
    md_path = diagrams_dir / f"{stem}.md"
    png_path = diagrams_dir / f"{stem}.png"

    mmd_path.write_text(mermaid.rstrip() + "\n", encoding="utf-8")
    html_path.write_text(build_mermaid_html(mermaid, title=title), encoding="utf-8")
    md_path.write_text(
        build_package_md(
            title=title,
            subtitle=subtitle,
            mermaid=mermaid,
            stem=stem,
        ),
        encoding="utf-8",
    )
    out: dict[str, Path] = {
        "html": html_path,
        "md": md_path,
        "mmd": mmd_path,
    }
    ir = None
    try:
        ir = screenshot_html(html_path, png_path, scale=scale)
        out["png"] = png_path
    except RenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        err = classify_render_error(exc)
        raise RenderError(err.kind, f"html/md/mmd 已写入，但 PNG 截图失败：{err}", err.detail) from exc
    # 保证返回键顺序与 STANDARD_OUTPUTS 一致
    paths = {
        "png": out["png"],
        "html": out["html"],
        "md": out["md"],
        "mmd": out["mmd"],
    }
    return attach_graph_ir_and_extras(
        paths,
        stem,
        diagrams_dir,
        ir=ir,
        with_drawio=with_drawio,
        with_pptx=with_pptx,
    )


def render_layered_files(
    data: dict[str, Any],
    stem: str = "skill_diagram_architecture",
    diagrams_dir: Path = DIAGRAMS_DIR,
    scale: float = 3.0,
    with_drawio: bool = False,
    with_pptx: bool = False,
) -> dict[str, Path]:
    """固定导出：png + html + md + mmd（另附 json 中间产物）。"""
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    title = str(data.get("title") or "技术架构图")
    subtitle = str(data.get("subtitle") or "分层色块架构")
    mermaid = layered_json_to_mermaid(data)

    json_path = diagrams_dir / f"{stem}.json"
    html_path = diagrams_dir / f"{stem}.html"
    md_path = diagrams_dir / f"{stem}.md"
    mmd_path = diagrams_dir / f"{stem}.mmd"
    png_path = diagrams_dir / f"{stem}.png"

    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(build_layered_html(data), encoding="utf-8")
    mmd_path.write_text(mermaid, encoding="utf-8")
    md_path.write_text(
        build_package_md(
            title=title,
            subtitle=subtitle,
            mermaid=mermaid,
            stem=stem,
            extra_note=(
                "HTML/PNG 为分层色块产品图风格；`.mmd` 由同一 JSON 自动转换，便于二次编辑。"
            ),
        ),
        encoding="utf-8",
    )
    ir = None
    try:
        ir = screenshot_html(html_path, png_path, scale=scale)
    except RenderError:
        raise
    except Exception as exc:  # noqa: BLE001
        err = classify_render_error(exc)
        raise RenderError(err.kind, f"html/md/mmd/json 已写入，但 PNG 截图失败：{err}", err.detail) from exc
    paths = {
        "png": png_path,
        "html": html_path,
        "md": md_path,
        "mmd": mmd_path,
        "json": json_path,
    }
    return attach_graph_ir_and_extras(
        paths,
        stem,
        diagrams_dir,
        ir=ir,
        layered_data=data,
        with_drawio=with_drawio,
        with_pptx=with_pptx,
    )


def render_from_assistant_text(
    assistant_text: str,
    renderer: str = "mermaid",
    stem: Optional[str] = None,
    title: str = "技术架构图",
    name_hint: Optional[str] = None,
    diagram_name: Optional[str] = None,
    diagrams_dir: Path = DIAGRAMS_DIR,
    with_drawio: bool = False,
    with_pptx: bool = False,
) -> dict[str, Path]:
    """渲染并按「名称_日期_Vn」落盘；stem 若传入则跳过自动版本号。"""
    diagrams_dir = Path(diagrams_dir)
    if renderer == "layered_html":
        data = extract_json_object(assistant_text)
        if not data or "layers" not in data:
            raise ValueError("架构图样式需要 JSON（含 layers 字段），当前输出无法解析")
        name = diagram_name or derive_diagram_name(
            data=data, title=title, name_hint=name_hint
        )
        out_stem = stem or allocate_versioned_stem(name, diagrams_dir=diagrams_dir)
        paths = render_layered_files(
            data,
            stem=out_stem,
            diagrams_dir=diagrams_dir,
            with_drawio=with_drawio,
            with_pptx=with_pptx,
        )
        paths["stem"] = out_stem  # type: ignore[assignment]
        return paths

    mermaid = extract_mermaid(assistant_text)
    if not mermaid:
        raise ValueError("未找到 ```mermaid 代码块，无法渲染")
    name = diagram_name or derive_diagram_name(
        title=title, mermaid=mermaid, name_hint=name_hint
    )
    out_stem = stem or allocate_versioned_stem(name, diagrams_dir=diagrams_dir)
    paths = render_mermaid_files(
        mermaid,
        stem=out_stem,
        title=name,
        diagrams_dir=diagrams_dir,
        with_drawio=with_drawio,
        with_pptx=with_pptx,
    )
    paths["stem"] = out_stem  # type: ignore[assignment]
    return paths


def render_from_skill_log(
    log_path: str | Path = "logs/skill_output.txt",
    stem: Optional[str] = None,
    title: str = "技术架构图",
    renderer: str = "mermaid",
    name_hint: Optional[str] = None,
    diagram_name: Optional[str] = None,
    diagrams_dir: Path = DIAGRAMS_DIR,
    with_drawio: bool = False,
    with_pptx: bool = False,
) -> dict[str, Path]:
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到日志：{path}")
    assistant = extract_latest_assistant(path.read_text(encoding="utf-8"))
    return render_from_assistant_text(
        assistant,
        renderer=renderer,
        stem=stem,
        title=title,
        name_hint=name_hint,
        diagram_name=diagram_name,
        diagrams_dir=diagrams_dir,
        with_drawio=with_drawio,
        with_pptx=with_pptx,
    )
