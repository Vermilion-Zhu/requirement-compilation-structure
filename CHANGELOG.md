# Requirement Compilation Agent — 整合说明

一份面向提交与评审的简要说明：这个 agent 是什么、本版改了什么、如何运行与上传、当前验证到哪一步。
详细分析见 `docs/`（该目录不纳入版本库）：

- `docs/arc-bench-upload-gaps-and-improvements.md` — 三个版本（官方 Blank / 已跑通版 / 当前实现）的对比、
  上传阻塞点逐条分析、以及依据 `principle.md` 的改进方向
- `docs/arc-bench-step1-changes.md` — 第一步改动的完整日志与验证过程

---

## 1. 这是什么

一个把**需求文档编译成可运行 Web 应用**的 agent。它不直接"让模型写一个网站"，而是按固定 pass 顺序
把需求编译成带契约的中间表示，再用真实测试驱动局部实现：

```
需求树 → DB Schema → 数据读写义务(Ω) → 后端 API 契约(I/O/R/W/P/Q)
      → SQL 与启动数据 → 后端 HTTP 测试与实现 → UI/数据设计 → UI 存在性测试与实现
      → Trigger 设计 → 端到端测试、独立验收与修复
```

13 个 pass 的产物全部落在 `<应用输出目录>/.arc/`，每步都有结构化 JSON、编译日志和 Git checkpoint，
失败不会中断后续 pass，报告写在 `.arc/compilation.json`。

技术栈：Python（agent）+ 生成的 TypeScript 应用（React + Vite + Express + SQLite，
根 npm workspaces + `deploy.sh`）。

---

## 2. 本版改了什么（ARC-Bench 上线阻塞项）

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **M2a** | `compiler.py` 靠 `import_module("00_project_initialization")` 找 pass，入口只存在于根目录教学脚本，ZIP 少带一个就全线崩 | 13 个 pass 下沉到 `infrastructure/stages/passes/`，`compiler.py` 通过 `PASS_MODULES` 注册表解析；根脚本瘦身为 360 行纯 CLI，报告键名与 `Stage NN` 标签保持不变 |
| **M3a** | 平台会预注入任务基线（`backend/`、`frontend/` 包名不同），原实现"只创建不覆盖"导致两套脚手架混装，`npm run build` 必挂 | 00 阶段先分类 `empty / scaffold / foreign`；foreign 时把冲突项**移动**（不删除）到 `.arc/baseline_backup/<时间戳>/`，写 `.arc/baseline_handling.json`；`ARC_KEEP_BASELINE=1` 可跳过接管 |
| **M4** | `deploy.sh` 契约要求遵守 HOST/PORT，原实现只用 PORT；且每次启动都重装依赖 | `server.ts` 绑定 `HOST ?? "0.0.0.0"`；`deploy.sh` 回显并导出 HOST/PORT，检测到已安装的 workspace 时跳过 `npm install` |
| **M5** | 任何异常都 `SystemExit(0)`，平台无法区分"部分完成"和"什么都没产出" | 有 `deploy.sh` + `package.json` → 0；无产物 → 1；Ctrl-C → 130；用法错误 → 2 |
| **M6** | 不认 `--type`（平台一旦传就 argparse 报错退出），完全不读 `ARCBENCH_*` | 接受 `--type` / `ARCBENCH_TASK_TYPE`，位置参数与输出目录可用 `ARCBENCH_TASK_DIR` / `ARCBENCH_OUTPUT_DIR` 兜底；非 web 任务提前失败并说明原因 |
| **M7** | 恒发 `max_completion_tokens=320000`，且强制 `response_format=json_object`，任一被端点拒绝就 13 个 pass 全 FAILED；`MODEL` 也可能未被注入 | 默认不发送输出上限（仅显式设置时发送）；`response_format` 被拒时降级为 prompt-only 并**重建提示词**重试；宽容解析 Markdown 围栏；模型名回退 `deepseek-flash`；平台运行时不再读本地 `.env` |
| **M7b** | `dict \| None` 注解在 import 期求值，Python < 3.10 会 `TypeError` | 相关模块统一补 `from __future__ import annotations` |

改动集中在：`main.py`、`infrastructure/compiler.py`、`infrastructure/stages/passes/`、
`infrastructure/shared/project/{initialize,git}.py`、`infrastructure/shared/project/templates/`、
`infrastructure/shared/models/{text,vision,configuration}.py`。

**算法本身没有改动**：pass 顺序、提示词、IR 结构、验证策略与上一版一致。这一版只保证"能上传、能启动、能出分"。

---

## 3. 与平台契约的对齐点

| 契约 | 本实现 |
| --- | --- |
| 入口 | `python3 main.py <需求目录> --output-dir <应用根>`；`main.py` 与 `requirements.txt` 在 ZIP 根 |
| 输入 | 读 `<需求目录>/requirements.yaml`（含引用图片），不写死 `input/` |
| 输出 | 应用直接写进 `--output-dir`，不再套一层；产物与 `.arc/` 同处应用根 |
| 启动 | 保留 `package.json` + `deploy.sh` + `frontend/` + `backend/` 结构；平台执行 `bash deploy.sh` |
| 端口 | 遵守注入的 `PORT`；未注入时默认 3000，监听 `0.0.0.0` |
| 模型 | 只读 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `MODEL`；不写死地址或 Key；平台环境下不覆盖注入值 |
| 依赖 | agent 依赖在根 `requirements.txt`（PyYAML / openai / python-dotenv / httpx / rich / Pillow），应用依赖在应用自己的 `package.json` |

---

## 4. 本地运行与上传

```powershell
# 环境（Node.js 22.12+ / npm / uv）
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # 填 OPENAI_*、MODEL、MAX_OUTPUT_TOKENS(可留空)
uv run playwright install chromium

# 编译
uv run main.py ./input --output-dir ./output/demo

# 启动生成的应用
cd output/demo; bash deploy.sh
```

也可以逐个 pass 跑（教学入口仍然可用）：`uv run 00_project_initialization.py --input input --output output/demo`，
`uv run 01_explore_requirement.py ...` 依此类推。

打包上传：

```powershell
uv run python scripts\package.py -o compiler.zip
```

脚本按 Git ignore 规则裁剪，`.venv/`、`output/`、`docs/`、真实 `.env`、`*.zip` 都不会进包。
当前包约 223 条目 / 4 MB（大头是示例目录 `input/`，非必需）。

---

## 5. 验证状态

**已验证**

- 打包脚本产出结构正确的 ZIP（`main.py`、`requirements.txt`、`infrastructure/stages/passes/`、
  模板与 `deploy.sh` 齐全；无 `.env`/`.venv`/`output/`）。
- 与改动前的 HEAD 逐条对比测试结果：**0 回归**，7 条原本失败的用例转为通过
  （145 → 170 条用例，其中 25 条为本次新增）。
- 模拟平台调用：用官方模板冒充注入基线执行 00 阶段，基线被完整移入备份目录，
  生成的 `backend/package.json` 为 `@arc/backend`、`frontend/package.json` 为 `@arc/frontend`，
  `deploy.sh` 通过 `bash -n`。
- **Smoke Competition 已完成一次端到端运行**（本版即该次提交所用代码），确认了本地无法验证的三件事：
  模型参数被代理接受、Chromium 可在容器内安装、`deploy.sh` 能在容器内构建并启动。

**已知限制**

- 仓库原有 37 条失败用例（HEAD 即存在，多为导入缺失与本地 fake 问题）未修复，会掩盖后续回归。
- 尚未接入 `arcbench_agent_runtime`：网站上看不到逐需求状态与追溯视图。
- `install_dependencies` 在 05/08/10/12 最多触发 4 次、Chromium 最多装 2 次，长任务有超时风险。
- 只支持 web 任务；`cli` / `android` 会明确失败而不是给出错误结果。

---

## 6. 下一步

1. **预算与稳定性**：依赖安装加指纹缓存、Chromium 只装一次、把 `--max-turns/--max-tests` 暴露给入口。
2. **输入健壮性**：读 `requirements.md` / `prerequisites.md` / `assets/`，缺失图片降级为 warning，
   先把需求 AST 落盘再做校验。
3. **可视化**：接入 `arcbench_agent_runtime`，把 pass 边界与 Git checkpoint 映射成需求状态事件。
4. **算法改进**（见 `principle.md` 与详细分析）：把 Ω 做成带生命周期与证据的一等状态、
   给声明式 R/W 补上"实际访问"的静态检查、实现 Reference 的 data/state 两种语义、
   用有界定点迭代替代"失败就往下走"。
