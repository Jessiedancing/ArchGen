# ArchGen 0.4.0 · Mac 使用说明

把系统说明贴进去，生成本地架构图 / 流程图等。内容只发到你自己填的模型地址，不走公有云。

本包只给 **macOS**。Windows 请用 `ArchGen-win-green-v0.4.0.zip`。

## 你需要先有的三样东西

1. **Python 3.10 或更高**：[python.org/downloads](https://www.python.org/downloads/) 或终端执行 `brew install python`
2. **Chrome 或 Edge**（出 PNG 图要用；**只有 Safari 出不了图**）
3. **一个能聊天的模型服务**（三选一）  
   - 本机 [LM Studio](https://lmstudio.ai/)：Developer / Local Server 点 Start，地址一般是 `http://localhost:1234/v1`  
   - 本机 [Ollama](https://ollama.com/)：地址一般是 `http://localhost:11434/v1`  
   - 公司私有网关：问管理员要地址、密钥、模型名

## 第一次（只需做一遍）

1. 解压 zip 到任意位置（不要放进权限很怪的目录）。
2. 若双击提示「已损坏 / 无法打开」：打开「终端」，进入解压后的文件夹，执行：

   ```bash
   xattr -cr .
   ```

   然后再双击启动器。
3. 双击 **`首次安装依赖.command`**  
   - 若提示无法打开：在终端执行 `chmod +x "首次安装依赖.command" "启动 ArchGen.command"` 后再试  
   - 会装 Python 依赖并下载 Chromium，等到提示完成
4. 确认模型软件已经启动（LM Studio 要看到服务在跑、模型已 Load）。

## 以后每次使用

1. 双击 **`启动 ArchGen.command`**  
   或在系统「**终端**」App（不要用 Cursor 内置终端）里执行：

   ```bash
   python3 desktop/app.py
   ```

   **不要在 Cursor 里启动**：沙箱会强杀 Chrome，看起来像渲染失败。
2. **不要关那个终端窗口**，关了网页就打不开
3. 浏览器会打开 `http://127.0.0.1:8765/`  
   若地址栏出现「已翻译成××」：点翻译图标 → **不翻译此网站**
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

都在本包的 `userdata/`，升级时只要保留这个文件夹就不会丢：

- `userdata/config.json` — 网关设置
- `userdata/diagrams/` — png / html / md / mmd
- `userdata/logs/` — 失败时搜「渲染失败」

界面上也可以点「打开文件夹」。

## 为什么点了生成要等好几分钟？

「测试连通」快、出图慢是正常的：探测只回一句 ok，出图要写完整张图。本机大模型（尤其没开 GPU）常要 3～10 分钟。看「终端」是否在逐字出内容、LM Studio 的 token 是否在涨；两边都在动就继续等。

## 常见问题

| 现象 | 怎么办 |
|---|---|
| 提示找不到 python3 | 安装 Python 3，或 `brew install python` |
| 双击 .command 闪退 / 无法打开 | `chmod +x "启动 ArchGen.command"`；仍提示损坏则 `xattr -cr .` |
| 设置页文字奇怪 | 关掉浏览器「翻译此页」 |
| 测试当前档失败 | 先确认 LM Studio / Ollama / 网关还在跑，BASE_URL 带 `/v1`，MODEL 抄对 |
| 能出文字但不能出 PNG | 用系统「终端」或双击 .command（不要用 Cursor）；再装 Chrome 或 Edge，不要只用 Safari |

## 安全

服务只监听本机 `127.0.0.1`。推理只发到你在设置里填的地址。密钥只存在本地 `userdata/config.json`。
