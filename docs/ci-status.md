# CI 状态与本地运行说明

更新：2026-10-24。本文记录 CI 到底跑没跑、本机怎么跑、以及失败项的真实原因。结论先行：**GitHub Actions 从未运行过**（仓库没有 remote）；本地按 CI 的两条命令手工跑过，后端全绿，前端 86 项中 84 项通过，2 项因环境原因失败。

## 1. 现在的真实状态

| 项目 | 状态 | 说明 |
|---|---|---|
| GitHub Actions | **未运行过** | 仓库没有配置 git remote，`.github/workflows/ci.yml` 只会在推送到 GitHub 后触发；本地无法验证 runner 上的行为 |
| 后端测试（本地） | ✅ 228 passed | `python -m pytest -q` |
| 前端测试（本地） | ⚠️ 83/85 passed | `node --test tests/*.test.cjs` |

## 2. 本机要用的确切命令

Node 不要用 `node` 裸命令：这台机器的 `node` 是 mise 的 shim，会连带触发无关工具安装并失败。用绝对路径：

```powershell
# 后端
cd C:\Users\许昀\WeChatProjects\miniprogram-1\backend
.\.venv\Scripts\python.exe -m pytest -q

# 前端
cd C:\Users\许昀\WeChatProjects\miniprogram-1
& "C:\Users\许昀\.local\share\mise\installs\node\24.21.0\node.exe" --test tests/*.test.cjs
```

- Node 位置：`C:\Users\许昀\.local\share\mise\installs\node\24.21.0\node.exe`（全盘只找到这一份可用的 node 运行时；微信开发者工具自带的不是独立 runtime）。
- 前端测试必须用 `tests/*.test.cjs` 这种 glob，`node --test tests/` 在 Windows 上会把目录当成单个测试文件而报 "test failed"。CI 里已同步改成 glob。

## 3. 为什么本地要“放行权限”才能跑完

DSH 的会话沙箱在 Windows 上禁止两类操作，会让部分用例直接失败：

1. **创建子进程管道**（`CreatePipe` → `WinError 5`）：任何需要起子进程并读取其输出的用例（OCR worker、MCP 桥、`cli` 调用）都会失败。
2. **在沙箱创建的临时目录里读写**：pytest 的 `tmp_path` 目录建完即不可读（`PermissionError`），导致依赖 `tmp_path` 的用例在 setup 阶段报错。

因此本机跑全量测试需要用 `danger-full-access`（放行权限）。这不是代码缺陷，普通终端 / CI runner 上没有这个限制。

## 4. 两个未通过的前端用例

```
✖ native home handlers execute health and medicine workflow against actual HTTP
✖ native page handlers run actual HTTP upload → CPU OCR → correction → archive → history → regrant
```

现象与定位：

- 两个用例都会自己 `spawn` 一个 uvicorn（`app.main:app`），用 `YIFAZHILIAN_DB_PATH` 指向 `os.tmpdir()` 下新建的临时目录，然后走真实 HTTP。
- 页面拿到的响应是 `500 Internal Server Error`；打开子进程 stderr 后看到根因：
  `sqlite3.OperationalError: unable to open database file`
- 也就是说：服务端在**测试临时目录**里建不了 SQLite 文件，请求在 `Database.initialize()` 就失败了，页面再拿到非 JSON 的错误页，于是 `JSON.parse('Internal S...')` 报错。
- 已排除的方向：同一台机器上手动用工作区目录做 `YIFAZHILIAN_DB_PATH` 起服务时一切正常（demo-login / users/me 都是 200），说明不是迁移或接口代码的问题。
- 高度怀疑仍与本节第 3 条的沙箱临时目录策略有关（Node 创建的临时目录 → Python 子进程写入被拒），但没有单独验证；这两个用例也不在本次改动范围内。

**补验方法**：在一台没有沙箱限制的机器（或 CI runner）上跑同一条前端命令，若这两项通过即可判定为本机环境问题。

## 5. 后续要补的

- 给仓库加 remote 并推送一次，让 Actions 真正跑起来，把“本地能跑”变成“runner 能跑”。
- 在 `ci.yml` 里补上后端 OCR 依赖（`requirements-ocr.txt` + `.ocr-venv`），否则 runner 上这两个 HTTP 用例会被跳过而非执行。
