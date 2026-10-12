"""私有网关调用层：配置加载、模型解析、流式对话、结果落盘。

被 main.py（提示词测试台）与 diagram_cli.py（图表 CLI）共用。
只与 .env 中的 BASE_URL 通信，不内置任何公开模型地址。
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from typing import Optional

from pathlib import Path

import httpx
import openai

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.S | re.I)
_NON_CHAT_MODEL = re.compile(r"embed|rerank|reranker", re.I)

# 引擎目录：.env 属引擎侧配置，从任意 cwd（含 MCP 子进程）调用时兜底到这里（T14.1）
ENGINE_ROOT = Path(__file__).resolve().parent
ENV_FILE = ".env"
RECORD_SEPARATOR = "=" * 60


def resolve_env_path(env_path: str = ENV_FILE) -> Path:
    """定位 .env：优先调用方 cwd（用户显式覆盖），否则回退引擎目录。

    这样 MCP / 从任意目录启动时仍能读到引擎旁的 .env，而在某个项目目录里
    放了自己的 .env 时又能就地覆盖，符合用户预期。
    """
    p = Path(env_path)
    if p.exists():
        return p
    if not p.is_absolute():
        candidate = ENGINE_ROOT / p
        if candidate.exists():
            return candidate
    return p


def safe_print(text: str) -> None:
    """避免 Windows 控制台 GBK 编码导致 emoji 等字符打印崩溃。"""
    try:
        print(text, end="", flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding), end="", flush=True)


def validate_base_url(url: str) -> Optional[str]:
    """检查 BASE_URL 格式。不合法返回中文原因，合法返回 None（A-02）。"""
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return "请填写 BASE_URL"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return "BASE_URL 须以 http:// 或 https:// 开头"
    host = parsed.hostname or ""
    if not host:
        return "BASE_URL 缺少主机名"
    if re.fullmatch(r"\d+\.\d+\.\d+", host):
        return f"地址不完整：{host} 不是合法主机名（本机请用 127.0.0.1）"
    if host == "127.0.0":
        return "地址不完整：127.0.0 不是合法主机名（本机请用 127.0.0.1）"
    return None


def classify_probe_failure(exc: BaseException, base_url: str) -> str:
    """探测失败：先判格式，再判服务没起（A-02）。"""
    fmt = validate_base_url(base_url)
    if fmt:
        return f"地址格式不对：{fmt}"
    text = str(exc)
    lowered = text.lower()
    if any(k in lowered for k in ("connect", "connection", "refused", "timed out", "timeout", "name or service")):
        return (
            f"地址格式正确，但服务没起来。请确认网关或 LM Studio 已启动：{base_url}\n{text}"
        )
    return text


def env_bool(env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def strip_reasoning(text: str) -> str:
    """去掉思考段，避免 <think> / reasoning 里的花括号污染 JSON（T07）。"""
    if not text:
        return ""
    return _THINK_RE.sub("", text).strip()


def is_chat_model_id(model_id: str) -> bool:
    """过滤 embedding / rerank，避免下拉选中后请求失败（T07）。"""
    return bool(model_id) and not _NON_CHAT_MODEL.search(model_id)


def _load_env_file(path: Path, env: dict) -> dict:
    if not path.exists():
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def load_env(env_path: str = ENV_FILE, profile: Optional[str] = None) -> dict:
    """加载 .env。`--profile name` 读 `.env.name`，不存在则回退 `.env`（T07）。"""
    env = dict(os.environ)
    if profile:
        named = profile if str(profile).startswith(".env") else f".env.{profile}"
        named_path = resolve_env_path(named)
        if named_path.exists():
            return _load_env_file(named_path, env)
    return _load_env_file(resolve_env_path(env_path), env)


def parse_model_catalog(env: dict) -> dict[str, str]:
    """
    解析私有模型目录。
    MODELS 格式：别名=真实模型名，多项用逗号或换行分隔。
    例：qwen=Qwen3.5-27B,glm=glm-5.2
    若未配置 MODELS，则仅包含默认 MODEL。
    """
    catalog: dict[str, str] = {}
    raw = (env.get("MODELS") or "").strip()
    if raw:
        for part in raw.replace("\n", ",").split(","):
            item = part.strip()
            if not item:
                continue
            if "=" in item:
                alias, name = item.split("=", 1)
                alias, name = alias.strip(), name.strip()
                if alias and name:
                    catalog[alias] = name
                    catalog[name] = name
            else:
                catalog[item] = item

    default_model = (env.get("MODEL") or "").strip()
    if default_model:
        catalog.setdefault(default_model, default_model)
        catalog.setdefault("default", default_model)
    return catalog


def resolve_model(requested: Optional[str], env: dict) -> str:
    """把别名或真实名解析成请求用的 model 字符串。"""
    catalog = parse_model_catalog(env)
    default_model = (env.get("MODEL") or "").strip()
    if not requested or not requested.strip():
        if not default_model:
            raise ValueError("未配置 MODEL，且未通过 --model 指定模型")
        return default_model

    key = requested.strip()
    if key in catalog:
        return catalog[key]

    # 允许直接传网关真实模型名（即使不在 MODELS 列表里）
    return key


def read_text(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_tests(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} 格式错误：根节点应为数组")
    return data


def find_test(tests: list[dict], name: str) -> dict:
    for item in tests:
        if item.get("name") == name:
            return item
    available = ", ".join(item.get("name", "?") for item in tests)
    raise ValueError(f"找不到用例「{name}」。可用用例：{available}")


def validate_test(item: dict, index: int) -> None:
    required = ("name", "prompt", "user", "output")
    missing = [field for field in required if not item.get(field)]
    if missing:
        raise ValueError(f"tests.json 第 {index} 条缺少字段：{', '.join(missing)}")


def prepend_record(out_path: str, record: str) -> None:
    """把最新记录写到文件开头。"""
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    if not record.endswith("\n"):
        record += "\n"
    existing = ""
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            existing = f.read()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(record)
        f.write(existing)


def build_client(env: dict) -> tuple[openai.OpenAI, str]:
    """按 .env 创建只指向私有网关的客户端，返回 (client, base_url)。"""
    api_key = env.get("OPENAI_API_KEY")
    base_url = env.get("BASE_URL")
    if not api_key or not base_url:
        raise ValueError("缺少配置，请复制 .env.example 为 .env 并填写 OPENAI_API_KEY / BASE_URL")

    default_headers = {}
    api_version = env.get("API_VERSION")
    if api_version:
        default_headers["version"] = api_version

    ssl_verify = env_bool(env, "SSL_VERIFY", default=False)
    trust_env = env_bool(env, "TRUST_ENV", default=False)
    try:
        timeout = float(env.get("REQUEST_TIMEOUT") or "120")
    except ValueError:
        timeout = 120.0
    proxy = (env.get("PROXY") or "").strip()
    client_kwargs: dict = {
        "verify": ssl_verify,
        "trust_env": trust_env,
        "timeout": timeout,
    }
    if proxy:
        try:
            http_client = httpx.Client(**client_kwargs, proxy=proxy)
        except TypeError:
            http_client = httpx.Client(**client_kwargs, proxies=proxy)
    else:
        http_client = httpx.Client(**client_kwargs)
    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers=default_headers or None,
        http_client=http_client,
    )
    return client, base_url


def read_sampling(env: dict) -> tuple[float, Optional[int]]:
    try:
        temperature = float(env.get("TEMPERATURE", "0") or "0")
    except ValueError:
        temperature = 0.0
    seed_raw = env.get("SEED", "42")
    try:
        seed = int(seed_raw) if seed_raw not in (None, "") else None
    except ValueError:
        seed = 42
    return temperature, seed


def _is_param_4xx(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
    try:
        code = int(status)
    except (TypeError, ValueError):
        text = str(exc).lower()
        return "400" in text or "unsupported" in text or ("invalid" in text and "seed" in text)
    return code in (400, 404, 422)


def _delta_field(delta: object, name: str):
    if delta is None:
        return None
    if isinstance(delta, dict):
        return delta.get(name)
    return getattr(delta, name, None)


def _visible_delta_text(delta: object) -> str:
    """只取可见 content，忽略 reasoning / reasoning_content / thinking（T07）。"""
    for skip in ("reasoning", "reasoning_content", "thinking"):
        extra = _delta_field(delta, skip)
        if extra and not _delta_field(delta, "content"):
            return ""
    content = _delta_field(delta, "content")
    return content if isinstance(content, str) else ""


def list_gateway_models(client: openai.OpenAI) -> list[str]:
    """透传 GET /v1/models，过滤 embedding / rerank。"""
    try:
        listing = client.models.list()
        ids = [str(item.id) for item in getattr(listing, "data", []) or [] if getattr(item, "id", None)]
    except Exception:  # noqa: BLE001
        return []
    return [mid for mid in ids if is_chat_model_id(mid)]


def stream_completion(
    client: openai.OpenAI,
    model: str,
    messages: list[dict],
    temperature: float = 0.0,
    seed: Optional[int] = 42,
    echo: bool = True,
) -> str:
    """流式请求。echo=False 时不打印，供 --json 等需要干净 stdout 的场景使用。"""
    # temperature=0 + 固定 seed，降低同句多次运行的分类抖动
    kwargs = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if seed is not None:
        kwargs["seed"] = seed
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        if seed is not None and _is_param_4xx(exc):
            print("当前网关不支持 seed，已忽略", file=sys.stderr)
            kwargs.pop("seed", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise

    parts: list[str] = []
    for chunk in response:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        content = _visible_delta_text(delta)
        if content:
            parts.append(content)
            if echo:
                safe_print(content)
    if echo:
        print()
    return strip_reasoning("".join(parts))


def probe_model(
    client: openai.OpenAI,
    model: str,
    temperature: float = 0.0,
) -> tuple[bool, str]:
    """轻量探测模型是否可用。返回 (ok, message)。"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "只回复：ok"}],
            max_tokens=64,
            temperature=temperature,
            stream=False,
        )
        content = ""
        if response.choices:
            message = response.choices[0].message
            content = strip_reasoning(getattr(message, "content", None) or "")
        return True, content or "连接正常"
    except Exception as exc:  # noqa: BLE001 - 探测时需要展示网关原始错误
        return False, str(exc)


def run_case(
    client: openai.OpenAI,
    model: str,
    base_url: str,
    name: str,
    prompt_path: str,
    user_path: str,
    out_path: str,
    temperature: float = 0.0,
    seed: Optional[int] = 42,
) -> None:
    system_prompt = read_text(prompt_path)
    user_input = read_text(user_path)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"\n{RECORD_SEPARATOR}\n"
        f"[时间] {timestamp}\n"
        f"[用例] {name}\n"
        f"[模型] {model}\n"
        f"[地址] {base_url}\n"
        f"[temperature] {temperature}\n"
        f"[seed] {seed}\n"
        f"[system文件] {prompt_path}\n"
        f"[user文件] {user_path}\n"
        f"{'-' * 60}\n"
        f"[system]\n{system_prompt}\n"
        f"{'-' * 60}\n"
        f"[user]\n{user_input}\n"
        f"{'-' * 60}\n"
        f"[assistant]\n"
    )

    print(f"\n>>> 正在运行：{name}")
    print(f">>> 模型：{model}")
    print(f">>> system：{prompt_path}")
    print(f">>> user：{user_path}")
    print(f">>> 输出文件：{out_path}\n")

    output = stream_completion(
        client, model, messages, temperature=temperature, seed=seed
    )
    body = output if output.endswith("\n") else output + "\n"
    prepend_record(out_path, header + body + "\n")


def print_model_help(
    env: dict,
    client: Optional[openai.OpenAI],
    temperature: float = 0.0,
) -> None:
    catalog = parse_model_catalog(env)
    default_model = (env.get("MODEL") or "").strip() or "(未配置)"
    print(f"默认 MODEL：{default_model}")
    print(f"网关 BASE_URL：{env.get('BASE_URL', '')}")
    print("说明：部分网关 /models 列表接口不可用；切换靠请求里的 model 字段。")
    print("配置的私有模型目录（来自 MODELS / MODEL）：")
    if not catalog:
        print("  (空) 请在 .env 配置 MODEL 或 MODELS")
    else:
        # 去重展示：优先展示别名映射
        shown = set()
        for alias, name in sorted(catalog.items()):
            if alias in ("default",) or alias == name:
                continue
            print(f"  别名 {alias} -> {name}")
            shown.add(name)
        for alias, name in sorted(catalog.items()):
            if alias == name and name not in shown:
                print(f"  {name}")
                shown.add(name)

    if client is None:
        return

    print("\n探测可用性：")
    names = sorted({name for name in catalog.values()})
    if not names and default_model != "(未配置)":
        names = [default_model]
    for name in names:
        ok, msg = probe_model(client, name, temperature=temperature)
        status = "可用" if ok else "不可用"
        detail = msg if ok else msg.split("\n")[0][:180]
        print(f"  [{status}] {name}  {detail}")
