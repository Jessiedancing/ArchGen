# 接入各类 Agent 工具

ArchGen 提供三种接入方式，覆盖目前主流 Agent 平台。选一种即可。

| 方式 | 适合 | 文件 |
|------|------|------|
| MCP 服务 | Codex、Cursor、Claude Desktop 等支持 MCP 的工具 | `archgen_mcp.py` |
| 命令行 + 说明书 | 能执行 shell 的 Agent（WorkBuddy、各类 IDE Agent） | `AGENTS.md`、`skills/tech-diagram/SKILL.md` |
| Function Calling | 自建 Agent、千问办公等按工具 schema 注册的平台 | `skills/archgen_tool_schema.json` |

---

## 方式一：MCP（推荐）

零依赖 stdio 服务，暴露 `archgen_list_styles` / `archgen_create` / `archgen_rerender`。

```json
{
  "mcpServers": {
    "archgen": {
      "command": "python3",
      "args": ["/绝对路径/archgen_mcp.py"]
    }
  }
}
```

- **Codex**：写进 `~/.codex/config.toml` 的 MCP 配置或对应 JSON 配置
- **Cursor**：`.cursor/mcp.json`
- **Claude Desktop**：`claude_desktop_config.json`

自检：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 archgen_mcp.py
```

## 方式二：命令行 + 说明书

把 `AGENTS.md` 放到项目根目录，多数 Agent 会自动读取；Cursor 用户再拷一份 Skill：

```bash
mkdir -p .cursor/skills && cp -r skills/tech-diagram .cursor/skills/
```

Agent 只需执行：

```bash
python3 archgen.py --text "<原文>" --style architecture --json
```

`--json` 保证 stdout 是纯 JSON，过程日志走 stderr，解析不会串味。

## 方式三：Function Calling

`skills/archgen_tool_schema.json` 是 OpenAI 兼容的工具定义，注册后在你的后端按
`cli_mapping` 执行对应命令，把 stdout 原样回传给模型即可。

```python
import json, subprocess

def archgen_create(text, style, name=None, out_dir=None):
    cmd = ["python3", "archgen.py", "--text", text, "--style", style, "--json"]
    if name:
        cmd += ["--name", name]
    if out_dir:
        cmd += ["--out-dir", out_dir]
    done = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(done.stdout)
```

---

## 通用注意事项

- 所有方式共用同一套 `.env`，推理只发往你配置的 `BASE_URL`
- 首次使用需 `python3 -m playwright install chromium`（否则只出 html/md/mmd，缺 png）
- 产物写在 `diagrams/`，文件名 `{名称}_{YYYYMMDD}_V{n}`，历史版本不会被覆盖
- Agent 回答用户时，建议把四个文件路径都列出来，让用户自选格式
