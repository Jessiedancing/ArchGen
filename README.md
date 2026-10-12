# ArchGen

用**你自己的私有模型**把一段文本变成技术图表，一次导出 4 种格式。原文不出你的网络。

适合：需要频繁画架构图 / 流程图 / 时序图，同时对数据外发敏感的团队。

## 特性

- **只连你的网关**：推理请求仅发往 `.env` 里的 `BASE_URL`（任何 OpenAI 兼容端点，含本地 Ollama、vLLM、内网网关）
- **8 种图**：分层架构、流程、时序、数据流、部署拓扑、状态机、ER、技术解析图
- **本地绿色桌面版**：`python3 desktop/app.py` 或双击启动脚本，浏览器 UI 填私有网关即可出图
- **一次出四种格式**：`png`（高清截图）、`html`（可预览；Mermaid 图因内联运行时约 3.2MB，有意为之）、`md`（可粘文档）、`mmd`（可二次编辑）
- **版本化文件名**：`{名称}_{YYYYMMDD}_V{n}`，同名同日自动递增，不覆盖历史
- **语法自检**：Mermaid 输出先做校验，有问题自动让模型改一次再渲染
- **可接 Agent**：自带 MCP 服务、Skill 说明书与 function calling schema

## 快速开始

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium     # 截图用

cp .env.example .env                        # 填入你的网关地址与 key
python3 archgen.py --input examples/sample_input.txt --style architecture
```

产物在 `diagrams/`：

```
订单履约平台_技术架构图_20260908_V1.png
订单履约平台_技术架构图_20260908_V1.html
订单履约平台_技术架构图_20260908_V1.md
订单履约平台_技术架构图_20260908_V1.mmd
```

## 图种

| `--style` | 图 | 适用 |
|-----------|----|------|
| `architecture` | 分层色块架构图 | 系统分层、模块边界、外部依赖 |
| `flowchart` | 流程图 | 步骤、分支、审批流转 |
| `sequence` | 时序图 | 接口调用顺序、异步回调 |
| `dataflow` | 数据流图 | 采集、清洗、同步、数仓 |
| `deployment` | 部署拓扑图 | 机房、集群、灾备多活 |
| `state` | 状态机图 | 订单/审核/任务生命周期 |
| `er` | 实体关系图 | 数据模型、表关系 |
| `techflow` | 技术解析图 | RAG/链路讲解、编号步骤、在线+离线双轨 |

## 本地绿色桌面版

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 desktop/app.py
```

浏览器打开后在「设置」里填私有网关（本机 LM Studio 一般为 `http://localhost:1234/v1`）。

| 平台 | 首次 | 日常 |
|------|------|------|
| Windows | `首次安装依赖.bat` | `启动 ArchGen.bat` |
| macOS | `首次安装依赖.command` | `启动 ArchGen.command` |

说明见 `desktop/README-win.md` / `desktop/README-mac.md`。开发仓可用 `python3 build_desktop.py --platform mac|win|all` 打 zip。

## 常用命令

```bash
python3 archgen.py --list-styles                  # 看图种与交付格式
python3 archgen.py --list-models                  # 看已配模型并探测权限
python3 archgen.py -i doc.txt -s flowchart        # 流程图
python3 archgen.py -t "订单先风控再库存锁定" -s sequence   # 直接传文本
python3 archgen.py -i doc.txt -n 支付链路          # 自定义文件名前缀
python3 archgen.py --render-only -s architecture  # 不调模型，用上次结果重新导出
python3 archgen.py -f diagrams/x.mmd              # 手改源码后重新出图（架构图改 .json）
python3 archgen.py -i doc.txt --json              # 供 Agent 调用，stdout 纯 JSON
```

| 参数 | 说明 |
|------|------|
| `--input/-i` | 输入文本文件 |
| `--text/-t` | 直接传文本，替代 `--input` |
| `--style/-s` | 图种，见上表 |
| `--model/-m` | 覆盖 `.env` 的 `MODEL`，支持 `MODELS` 别名 |
| `--name/-n` | 文件名前缀，默认取图标题 |
| `--out-dir/-o` | 输出目录，默认 `diagrams/` |
| `--render-only` | 跳过模型，用上次模型输出重渲 |
| `--from-file/-f` | 跳过模型，渲染手工改过的 `.mmd` / `.json` |
| `--json` | stdout 只输出 JSON，便于程序解析 |
| `--retries` | 语法自检失败后的重试次数，默认 1 |

## 在 Agent 工具里用

支持 MCP、命令行 Skill、function calling 三种接入，详见 [INTEGRATIONS.md](INTEGRATIONS.md)。

最简方式（Cursor）：

```bash
mkdir -p .cursor/skills && cp -r skills/tech-diagram .cursor/skills/
```

MCP（Codex / Claude Desktop 等）：

```json
{ "mcpServers": { "archgen": { "command": "python3", "args": ["/绝对路径/archgen_mcp.py"] } } }
```

## 配置

```env
OPENAI_API_KEY=your-key
BASE_URL=https://your-private-gateway/v1
MODEL=your-model-name
MODELS=fast=your-small-model,pro=your-large-model
DIAGRAM_STYLE=architecture
```

## 加一种新图

1. 在 `diagram_styles/` 写一份 system 提示词
2. 在 `diagram_styles/styles.json` 注册：`name` / `use_when` / `system_prompt` / `renderer`
3. `renderer` 取 `mermaid`（模型产出 Mermaid）或 `layered_html`（模型产出分层 JSON）

不用改渲染代码。

## 依赖

Python 3.9+、`openai`、`httpx`、`playwright`（截图需要一次 `playwright install chromium`；也可回退到本机 Chrome / Edge）。

## 许可

MIT，详见 [LICENSE](LICENSE)。数据安全说明见 [SECURITY.md](SECURITY.md)。
