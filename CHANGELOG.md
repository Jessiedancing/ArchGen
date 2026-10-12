# 更新日志

## 0.4.0

- **双平台脚本绿色包**：Windows `启动 ArchGen.bat`（首行 `chcp 65001`）/ Mac `.command`；`build_desktop.py --platform mac|win|all`
- **Mermaid 运行时随包**：`vendor/mermaid.min.js` 内联进 html，断网可预览。Mermaid 类 `.html` 约 3.2MB 是有意为之（不再依赖 CDN）
- **设计 token 单源**：`design_tokens.json` 同时驱动 UI、架构图、Mermaid 主题
- **多环境档位**：桌面设置可保存多套网关（公司局域网 / 家里本地），切换不静默回退
- **按需导出**：GraphIR → draw.io / PPTX（16:9），以及把 PNG 当图片复制到剪贴板
- **渲染失败分类**：浏览器不可用 / Playwright 未装 / Mermaid 语法 / 超时；界面只留人话，技术明细进日志
- 路径锚定到代码目录，任意工作目录 / MCP 调用不再找不到样式与 vendor

## 0.3.0

- **本地绿色桌面版**：`desktop/` + `build_desktop.py`，解压后双击启动，浏览器打开 UI
- 设置页填写私有 `BASE_URL` / Key / Model，配置落在 `userdata/`（与代码隔离）
- 新增图种 **techflow（技术解析图）**：编号请求流、角色配色、在线/离线双轨
- 图种合计 8 种

## 0.2.0

- 更名为 **ArchGen**，CLI 入口 `archgen.py`
- 图种从 3 种扩到 7 种：新增数据流图、部署拓扑图、状态机图、实体关系图
- 新增 Mermaid / JSON 输出自检，发现问题自动让模型修正后重渲（`--retries`）
- 渲染阶段拦截 Mermaid 语法错误，不再导出「报错图」
- 新增 `--json` 结构化输出、`--text` 直接传文本
- 新增 `--from-file/-f`：手工改过的 `.mmd` / `.json` 可直接重新出图，不调模型
- 架构图版式重做：层标题条 + 能力分组框 + 独立能力块 + 层间箭头，列数按宽度自适应
- Agent 接入：MCP 服务 `archgen_mcp.py`、`AGENTS.md`、function calling schema

## 0.1.0

首个可用版本。

- 三种样式：分层色块架构图、流程图、时序图
- 固定导出四件套：`png` / `html` / `md` / `mmd`
- 版本化文件名：`{名称}_{YYYYMMDD}_V{n}`，同名同日自动递增
- 私有网关：仅请求 `.env` 中的 `BASE_URL`，支持模型别名与权限探测
- 截图回退：Playwright chromium → 本机 Chrome → Edge
