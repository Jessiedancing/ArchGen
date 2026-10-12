# ArchGen 0.4.0 · Windows 使用说明

把系统说明贴进去，生成本地架构图 / 流程图等。内容只发到你自己填的模型地址，不走公有云。

本包只给 **Windows 10 / 11**。Mac 请用 `ArchGen-mac-green-v0.4.0.zip`。

## 你需要先有的三样东西

1. **Python 3.10 或更高**：[python.org/downloads](https://www.python.org/downloads/)  
   安装时**必须勾选** `Add python.exe to PATH`，装完重开一次命令行。
2. **Chrome 或 Edge**（出 PNG 图要用；只有国内浏览器经常出不了图）
3. **一个能聊天的模型服务**（三选一）  
   - 本机 [LM Studio](https://lmstudio.ai/)：开发者 / Local Server 点 Start，地址一般是 `http://localhost:1234/v1`  
   - 本机 [Ollama](https://ollama.com/)：地址一般是 `http://localhost:11434/v1`  
   - 公司私有网关：问管理员要地址、密钥、模型名

## 第一次（只需做一遍）

1. 把 zip **解压到短路径**，例如 `D:\ArchGen`。不要解压到桌面很深的文件夹（中文图名可能撞上 Windows 260 字符限制）。
2. 双击 **`首次安装依赖.bat`**  
   - 若弹出蓝色 SmartScreen：点 **「更多信息 → 仍要运行」**  
   - 窗口里应是正常中文，不是乱码；会装 Python 依赖并下载 Chromium  
   - 等到提示「安装完成」再关窗口
3. 确认模型软件已经启动（LM Studio 要看到服务在跑、模型已 Load）。

## 以后每次使用

1. 双击 **`启动 ArchGen.bat`**（不要在 Cursor 里启动，沙箱会杀 Chrome，看起来像渲染失败）
2. **不要关那个黑色窗口**，关了网页就打不开
3. 浏览器会打开 `http://127.0.0.1:8765/`  
   若地址栏出现「已翻译成××」：点翻译图标 → **不翻译此网站**。否则按钮和选项会被译乱（例如 `false` 变成 `falsealse`）
4. 点右上角 **设置**，按下面表格填写 → **保存** → **测试当前档**
5. 测通后关掉设置。左侧选图种，中间写系统说明，点 **生成图表**

## 设置怎么填

### 本机 LM Studio（端口 1234，最常见）

| 栏 | 填什么 |
|---|---|
| 档位显示名 | `家里本地`（随意） |
| BASE_URL | `http://localhost:1234/v1`（`/v1` 不能丢） |
| OPENAI_API_KEY | `lm-studio`（本机不校验，但不能空） |
| MODEL | LM Studio 里**当前已加载**的模型 ID，原样抄 |
| MODELS | 空着 |
| SSL_VERIFY | `false` |
| REQUEST_TIMEOUT | `600`（本地模型冷启动慢） |
| TRUST_ENV | `false` |
| PROXY | 空着 |

MODEL 在 LM Studio 的 Local Server / 已加载模型列表里能看到。填完点「测试当前档」，通了会列出可用模型。

### 本机 Ollama（端口 11434）

| 栏 | 填什么 |
|---|---|
| BASE_URL | `http://localhost:11434/v1` |
| OPENAI_API_KEY | `ollama` |
| MODEL | 例如 `qwen2.5:14b`（以 `ollama list` 为准） |
| REQUEST_TIMEOUT | `600` |
| 其余 | 与上表相同 |

### 公司私有网关

管理员给什么填什么：`BASE_URL` 一般以 `/v1` 结尾，`OPENAI_API_KEY` 是密钥，`MODEL` 是模型名。云端超时可改成 `120`。

## 图和配置在哪

都在本包的 `userdata\`，升级时只要保留这个文件夹就不会丢：

- `userdata\config.json` — 网关设置
- `userdata\diagrams\` — png / html / md / mmd
- `userdata\logs\` — 失败时搜「渲染失败」

界面上也可以点「打开文件夹」。

## 为什么点了生成要等好几分钟？

「测试当前档」快、出图慢，这是正常的，不是 Windows 坏了。

- 探测只让模型回一句 `ok`（几十个 token），一两秒就能通。
- 出图要把整份架构/流程写成 JSON 或 Mermaid，本机 7B～20B（尤其 CPU、没开 GPU）经常 **3～10 分钟**，第一次加载模型更久。
- 若自检没通过，还会再让模型改一版，时间接近翻倍。
- 请看两处是否在动：① 黑色启动窗口是否在逐字出内容；② LM Studio 的 token / 速度是否在涨。两边都在动就继续等。两边都静止超过一两分钟，再检查模型是否还 Load、超时是否填了 `600`。

想快（按收益排序）：

1. **要几秒出图**：Windows 填和 Mac 同一套公司局域网 `BASE_URL` / `MODEL`。ArchGen 两边一样，快的是网关 GPU。
2. **本机必须快一截**：LM Studio 关掉 Thinking / 推理思考。Qwen3.5 开思考时一次会写出四千多 token，图本身往往只用几百。
3. **RTX 3060 Laptop 只有 6GB 显存**：9B Q4 约 7.2GB，**整模塞不进显卡**，只能一部分 GPU、一部分 CPU，所以会比 M4 上的 20B 还慢。M4 32GB 是统一内存，20B 能整模上加速器。这台 Windows 不要上 20B。换能整模进 6GB 的量化，例如 7B/8B 的 Q4，或 9B 的 Q3；上下文改成 4096，GPU Offload 拉满，给 KV 缓存留空。
4. 出图选「分层色块架构图」；只关 ArchGen 停不掉生成，要在 LM Studio 里停请求。

## 常见问题

| 现象 | 怎么办 |
|---|---|
| 提示找不到 python | 重装 Python，勾选 Add to PATH，然后**新开**一个窗口再双击 bat |
| SmartScreen 蓝屏 | 「更多信息 → 仍要运行」 |
| 窗口中文乱码 | 用系统「命令提示符」双击 bat，不要用很老的 PowerShell ISE |
| 设置页文字奇怪、选项被译乱 | 关掉 Chrome「翻译此页」 |
| 测试当前档失败 | 先确认 LM Studio / Ollama / 网关还在跑，BASE_URL 带 `/v1`，MODEL 抄对 |
| 能出文字但不能出 PNG | 用 bat 启动（不要用 Cursor）；再装 Chrome 或 Edge |
| 提示 Mermaid 语法错误 | 9B 等小模型常写出不合法流程图。点「打开文件夹」看 `.mmd`；或改选「分层色块架构图」再生成 |
| 路径过长报错 | 把整个文件夹挪到 `D:\ArchGen` |

## 安全

服务只监听本机 `127.0.0.1`。推理只发到你在设置里填的地址。密钥只存在本地 `userdata\config.json`。
