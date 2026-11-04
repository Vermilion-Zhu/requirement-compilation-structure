# Requirement Compilation Agent — 整合说明

一份面向提交与评审的简要说明：这个 agent 是什么、做过哪些改动、如何运行与上传、当前验证到哪一步。
详细分析见 `docs/`（该目录不纳入版本库）：

- `docs/arc-bench-upload-gaps-and-improvements.md` — 三个版本（官方 Blank / 已跑通版 / 当前实现）的对比、
  上传阻塞点逐条分析、以及依据 `principle.md` 的改进方向
- `docs/arc-bench-step1-changes.md` — 第一轮（上线阻塞项）的完整改动日志
- `docs/arc-bench-step2-changes.md` — 第二轮（稳健性与可观测性）的完整改动日志

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

## 2. 已完成的改动

### 2.1 第一轮：ARC-Bench 上线阻塞项

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **M2a** | `compiler.py` 靠 `import_module("00_project_initialization")` 找 pass，入口只存在于根目录教学脚本，ZIP 少带一个就全线崩 | 13 个 pass 下沉到 `infrastructure/stages/passes/`，`compiler.py` 通过 `PASS_MODULES` 注册表解析；根脚本瘦身为 360 行纯 CLI，报告键名与 `Stage NN` 标签保持不变 |
| **M3a** | 平台会预注入任务基线（`backend/`、`frontend/` 包名不同），原实现"只创建不覆盖"导致两套脚手架混装，`npm run build` 必挂 | 00 阶段先分类 `empty / scaffold / foreign`；foreign 时把冲突项**移动**（不删除）到 `.arc/baseline_backup/<时间戳>/`，写 `.arc/baseline_handling.json`；`ARC_KEEP_BASELINE=1` 可跳过接管 |
| **M4** | `deploy.sh` 契约要求遵守 HOST/PORT，原实现只用 PORT；且每次启动都重装依赖 | `server.ts` 绑定 `HOST ?? "0.0.0.0"`；`deploy.sh` 回显并导出 HOST/PORT，检测到已安装的 workspace 时跳过 `npm install` |
| **M5** | 任何异常都 `SystemExit(0)`，平台无法区分"部分完成"和"什么都没产出" | 有 `deploy.sh` + `package.json` → 0；无产物 → 1；Ctrl-C → 130；用法错误 → 2 |
| **M6** | 不认 `--type`（平台一旦传就 argparse 报错退出），完全不读 `ARCBENCH_*` | 接受 `--type` / `ARCBENCH_TASK_TYPE`，位置参数与输出目录可用 `ARCBENCH_TASK_DIR` / `ARCBENCH_OUTPUT_DIR` 兜底；非 web 任务提前失败并说明原因 |
| **M7** | 恒发 `max_completion_tokens=320000`，且强制 `response_format=json_object`，任一被端点拒绝就 13 个 pass 全 FAILED；`MODEL` 也可能未被注入 | 默认不发送输出上限（仅显式设置时发送）；`response_format` 被拒时降级为 prompt-only 并**重建提示词**重试；宽容解析 Markdown 围栏；模型名回退 `deepseek-flash`；平台运行时不再读本地 `.env` |
| **M7b** | `dict \| None` 注解在 import 期求值，Python < 3.10 会 `TypeError` | 相关模块统一补 `from __future__ import annotations` |

### 2.2 第二轮：稳健性与可观测性

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **M9 输入容错** | 只读 `requirements.yaml`；任何一张引用图缺失都会在**写出需求快照之前**抛错，导致 02–12 全部连锁失败；场景/步骤缺 `id` 会 `KeyError` | 新增 `stages/requirements/input_materials.py`：先落盘 `requirements.json`，再收集 `requirements.md` / `prerequisites.md` / `assets/` / `reference/` 到 `.arc/input_materials.json`；缺失、越界或格式错误的图片与材料只记 `.arc/input_warnings.json` 并在日志中以 `[INPUT WARNING]` 提示；`RequirementTree` 对缺失/重复 id、非字符串 `description`、非列表 `children` 做确定性归一化 |
| **S3 文案** | 运行期报错仍提示 "Run 00_project_initialization.py first"，线上看不到这个文件 | 全部改为 pass 名称，例如 "Run the project-initialization pass (00) first" |
| **S1 可视化为空** | 网站上没有逐需求状态、追溯视图与提交历史 | 内置 `arcbench-agent-runtime`（ZIP 根目录 + `requirements.txt` 的 `./arcbench-agent-runtime`），新增 `shared/project/runtime_events.py` 适配层：记录 run 状态、需求树、`DESIGNED / IMPLEMENTED / PASSED` 状态与提交历史刷新信号；SDK 缺失或目录不可写时**静默降级**，绝不影响编译 |
| **契约可视化** | `interfaces` / `tests` 两张表一直是空的，网站只能看到需求级状态 | 06 写入 API 契约（含需求归属），09 写入页面契约，11 写入 trigger 契约并回填 API 的 `callers`；08 / 10 / 12 写入后端、UI、E2E、独立验收四类测试行（含文件路径与通过状态），API 实现完成后回填 `implemented` 与实现文件 |
| **测试基线** | 仓库原有 47 条用例针对已被替换的契约（整文件替换、编译器托管 wiring、扁平 tool call），长期红着，掩盖真实回归 | 修好可由当前 API 表达的（导入、签名、tool 形状、`schemas()` 结构、httpx 超时断言）；其余以 `ARC_LEGACY_TESTS=1` 门控跳过并注明原因 |

测试现状：`211 tests, OK (skipped=48)`。其中 46 条为 legacy 门控，2 条为环境门控
（真实数据库运行时 / Chromium）。`ARC_LEGACY_TESTS=1` 可重新运行 legacy 用例，便于后续移植。

**算法本身没有改动**：pass 顺序、提示词、IR 结构、验证策略与前两版一致。这两轮只保证
"能上传、能启动、输入更脏也不崩、网站上看得见进度"。

---

## 3. 与平台契约的对齐点

| 契约 | 本实现 |
| --- | --- |
| 入口 | `python3 main.py <需求目录> --output-dir <应用根>`；`main.py` 与 `requirements.txt` 在 ZIP 根 |
| 输入 | 读 `<需求目录>/requirements.yaml` 及可选材料，不写死 `input/`；材料缺失不致命 |
| 输出 | 应用直接写进 `--output-dir`，不再套一层；产物与 `.arc/` 同处应用根 |
| 启动 | 保留 `package.json` + `deploy.sh` + `frontend/` + `backend/` 结构；平台执行 `bash deploy.sh` |
| 端口 | 遵守注入的 `PORT`；未注入时默认 3000，监听 `0.0.0.0` |
| 模型 | 只读 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `MODEL`；不写死地址或 Key；平台环境下不覆盖注入值 |
| 依赖 | agent 依赖在根 `requirements.txt`（含本地 SDK `./arcbench-agent-runtime`），应用依赖在应用自己的 `package.json` |
| 可视化 | `ARCBENCH_RUNNER_EVENTS_PATH` 的 JSONL 与 `ARCBENCH_TRACEABILITY_DIR` 的 7 张表由 `runtime_events` 写入 |

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
`arcbench-agent-runtime/` 必须随包（`requirements.txt` 以相对路径引用它）。

---

## 5. 验证状态

**已验证**

- 打包脚本产出结构正确的 ZIP（`main.py`、`requirements.txt`、`infrastructure/stages/passes/`、
  `arcbench-agent-runtime/`、模板与 `deploy.sh` 齐全；无 `.env`/`.venv`/`output/`）。
- 全部单元测试：`211 tests, OK (skipped=48)`，与改动前基线逐条对比 **0 回归**。
- 模拟平台调用：用官方模板冒充注入基线执行 00 阶段，基线被完整移入备份目录，
  生成的 `backend/package.json` 为 `@arc/backend`，`deploy.sh` 通过 `bash -n`。
- 本地无平台环境时：`ROOT`/`REQ` 树写入 7 张 traceability 表，`interfaces` / `tests` 表记录
  API/页面/trigger 契约与各类测试；`runner-events.jsonl` 记录 `runner_state` / `requirement_state`，
  缺失图片只产生 warning。
- **Smoke Competition 已完成一次端到端运行**（第一轮提交的代码），13/13 pass 完成、
  23/23 后端测试通过、UI 与端到端全绿；日志显示 98 次模型调用、输入 1.32M tokens
  （其中 63% 命中缓存）、输出 186k tokens，总耗时约 34.5 分钟。第 12 阶段占 47% 时间，
  其中大半是 E2E 反复起服务；依赖安装只额外发生 3 次、每次 8 秒（首次 42 秒），
  Chromium 只真正安装一次——**证实跳过 M8 是合理的**。

**已知限制**

- 46 条 legacy 用例尚未移植到当前契约（默认跳过，`ARC_LEGACY_TESTS=1` 可运行）。
- 契约与测试明细只覆盖到"一次运行"：重跑同一任务会覆盖行而不保留历史（历史由 Git 提交承担）。
- 依赖安装仍在 05/08/10/12 触发多次、Chromium 最多装 2 次：按当前选择**保持现状**，
  等后续练习出现真实超时再按需调整。
- 只支持 web 任务；`cli` / `android` 会明确失败而不是给出错误结果。

---

## 6. 下一步

1. **算法改进**（见 `principle.md` 与详细分析）：把 Ω 做成带生命周期与证据的一等状态、
   给声明式 R/W 补上"实际访问"的静态检查、实现 Reference 的 data/state 两种语义、
   用有界定点迭代替代"失败就往下走"。
2. **移植 legacy 用例**：按整文件替换、model-owned wiring、扁平 tool call 三条契约逐组重写。
3. **按新日志继续调优**（需要更多样本）：独立验收的 `max_turns` 余量偏小
   （本轮 REQ-2 用到 9/10），E2E 复用 server 可显著压缩第 12 阶段时间——两者都等更多练习数据再定。
