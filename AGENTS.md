# ArchGen · Agent 使用说明

任何 Agent 工具（Codex、Cursor、WorkBuddy、千问办公等）读到本文件后，
遇到「画架构图 / 流程图 / 时序图 / 数据流 / 部署拓扑 / 状态机 / ER 图」的需求，
都应调用本仓库的 ArchGen，而不是自己手写 Mermaid、也不要把原文发给公开模型。

## 调用方式

```bash
python3 archgen.py --text "<用户原文>" --style <图种> --json
```

`--json` 会让 stdout 只输出结构化结果（过程信息走 stderr），便于解析：

```json
{
  "ok": true,
  "style": "architecture",
  "stem": "订单履约平台_技术架构图_20260908_V1",
  "files": {
    "png": "diagrams/订单履约平台_技术架构图_20260908_V1.png",
    "html": "...",
    "md": "...",
    "mmd": "..."
  }
}
```

## 选型规则

| 需求 | `--style` |
|------|-----------|
| 系统分层、模块边界、外部依赖 | `architecture` |
| 步骤、分支、审批流转 | `flowchart` |
| 接口调用顺序、异步回调 | `sequence` |
| 采集/清洗/同步/数仓 | `dataflow` |
| 机房、集群、灾备部署 | `deployment` |
| 订单/审核/任务生命周期 | `state` |
| 数据模型、表关系 | `er` |
| RAG/Agent/链路讲解、编号请求流 | `techflow` |

不确定时先跑 `python3 archgen.py --list-styles --json` 看清单。

## 固定交付

每次成功都会生成同名四件套，回答用户时应把四个路径都给出：

| 格式 | 用途 |
|------|------|
| `.png` | 贴 PPT / 评审材料 |
| `.html` | 浏览器预览 |
| `.md` | 粘进文档（内含 Mermaid） |
| `.mmd` | 二次编辑 |

按需另出：`--with-drawio` → `.drawio`（原生形状）；`--with-pptx` → `.pptx`（需 python-pptx）。
复制进 PPT 的是图片，要改文字请下 PPTX。

文件名规则 `{名称}_{YYYYMMDD}_V{n}`，同名同日自动递增，不会覆盖历史版本。

## 约束

- 只依据用户给的原文，不编造系统、接口、依赖
- 推理只走 `.env` 里的 `BASE_URL`（用户自己的私有模型）
- 渲染失败时先看 stderr，多数是 Playwright 浏览器未安装：`python3 -m playwright install chromium`
- 想改图不重新推理：`python3 archgen.py --render-only --style <图种> --json`
- 用户手工改过 `.mmd` / `.json` 后重出：`python3 archgen.py -f <文件> --json`
