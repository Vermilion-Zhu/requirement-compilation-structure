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

### 2.3 第三轮：冒烟日志驱动的四项修正

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **读取权限** | 日志里有 10 次 `This task cannot read this file`，全部发生在第 12 阶段的独立验收生成/复核，白耗了修复轮次 | 验收任务的只读白名单补上编译器自有基础设施与元数据（三个 `package.json`、`db/initialize.ts`、`db/client.ts`、`playwright.e2e.config.ts`、`vite.e2e.config.ts`）；错误信息改为列出"本次可读文件"并明确"应用源码不可读，请改用任务证据"；验收提示词同步说明，避免反复重试 |
| **轮次预算** | 冒烟中 REQ-2 的独立验收用到 9/10 轮，接近耗尽 | 所有 agent 循环的 `max_turns` 默认值 10 → **20**（05 数据库修复、08 后端 TDD、10 UI TDD、12 触发器/验收），CLI 默认值同步；按"优先保证正确率"的要求，接受最坏情况下更长 |
| **E2E 启动开销** | 每次 E2E 都重新拉起 Vite + 后端 | 每个应用只起一对服务器并跨多次 E2E 复用：端口固定、后端源码指纹变化时才重启、数据库复用并由 fixture 每测例清空；Playwright 用 `reuseExistingServer` 跳过启动；失败自动回退并在本阶段停用复用，阶段结束 `stop_e2e_servers` 回收（并用 bookstack 真实产物本地复现后修好四处：Vite 相对路径、.arc 未建即写日志、重启后端复用已删除的临时目录、runner 后端未回收；runner 现在**完全静默**，执行模式只写 .arc/e2e-runs.jsonl，Playwright 报告解析另有前缀容错） |
| **日志分析工具** | 上一轮的分析是一次性脚本 | 新增 `scripts/analyze_log.py`：解析阶段耗时、检查命令分类与最慢项、模型调用/令牌/分阶段耗时、编辑轮次与拒绝、读取拒绝与被请求文件、依赖安装、Git checkpoint、最终状态；支持 `--json` 与 `--top`，并有单元测试 |

### 2.11 第十一轮：提交前语义探针（M10）

| 项 | 内容 |
| --- | --- |
| 功能 | `scripts/preflight.py --app <构建产物>`：从 `.arc` 的 requirements + ui_design 抽出静态路由页根、命名地标、Follow-in-navigation 角色和 `"X"(role=Y)` 契约，启动应用（或 `--base-url` 复用）并用应用自带 Playwright 在真实浏览器中检查；failures 阻断提交，warnings 需 `--strict` 才阻断 |
| 设计 | 检查分三层：静态路由页根可见（重定向视为 auth-gated 跳过）、入口 `/` 的区域内容 + 命名地标 + 导航项角色、其它需求控件作为 advisory warning |
| 验证 | 对 `breadcrumb_fixed_stackoverflow` 构建产物报出 3 个失败（入口无区域、Main navigation 缺失、Questions 是 link）；全量 316 tests |
| 文件 | `infrastructure/shared/project/preflight.py`、`preflight_probe.mjs`、`scripts/preflight.py`（`.gitignore` 放行）、`tests/test_preflight.py` |

### 2.10 第十轮：入口路由与命名地标/导航角色（M8、M9）

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **入口路由** | stackoverflow 外部 9/27：/ 只有占位 Home，没有 Question feed；内部测试只覆盖设计页面 | 设计/实现提示词要求入口路由是真实页面；semantic_issues 在需求提到 homepage 而设计无 route / 时报告 |
| **命名地标与导航角色** | 需求写 "Main navigation"/"Follow Questions"，设计与实现却是 "Primary navigation" + link，外部 helper 按 button 定位全部 10s 超时 | 抽取需求 "X"(role=Y)、定点 navigation、Follow X in Navigation 校验；导航项角色规则改为"需求称 link 才用 link，否则 button"；修复回合接收这些契约；status/alert 与 link/button 的 type 自动纠正 |
| **验证** | — | 在 readcrumb_fixed_stackoverflow 产物上报出导航名、Questions 角色、缺首页；在 keep 产物上报出 alert/status 冲突；全量 308 tests |



| 项 | 内容 |
| --- | --- |
| 重放点 | `pre-m4` 检查点（`b92f2a1`，bookstack 12/12）之上，保留 `8b4b5a0` 的导航守卫 |
| 合并 | M4 的 `state`/`status`/动态 name 与守卫的"仅壳声明主导航"共存：design/implementation 提示词合并为同一段，`semantic_issues` 同时保留状态校验与重复导航检查 |
| 测试 | `test_ui_semantics.py` 合并为 30 条（守卫 5 条 + M4 7 条 + 原有）；全量 289 tests |

### 2.8 第八轮：导航地标守卫（bookstack 回归修复）

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **第二个 navigation 地标** | bookstack 外部从 11/12 跌到 3/11：该轮设计把面包屑建模成 3 个页面级 `navigation`，每个都含 "Books" 链接；外部 `go()` 的 `getByRole('navigation').filter(has link 'Books').getByRole('link', {name:'Books'})` 解析到 2 个元素，9 条用例 strict-mode 失败 | 设计提示词明确"面包屑/分段切换器是页面内容（链接容器），只有应用壳声明主导航地标，除非需求显式要求面包屑导航地标"；实现提示词加同样例外；`semantic_issues` 新增"页面级 navigation 重复了壳导航链接名"的报告（用失败产物验证：恰好命中 3 个面包屑） |
| **回处理** | — | 回退 M1/M2/M4（`f87c13b`）→ 修复守卫（`8b4b5a0`）→ 重放 M1/M2（`661059c`）；M4 待守卫验证后重放 |

### 2.7 第七轮：M1 依赖可复现与 M2 等待预算

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **依赖漂移** | 模板 `tailwindcss: "^4.0.0"` 在平台镜像解析到 4.3.5，而 `@tailwindcss/oxide@4.3.5` 不存在：6 次 ETARGET、5 次安装失败、阶段 05 762 s、12 轮编辑 | 模板锁定到已验证的 `4.3.4`（含 `@tailwindcss/vite`）；`install_dependencies` 失败信息附 npm 输出尾部；新增 `ensure_database_dependencies`：同一 manifest 失败只报一次，不再重跑 npm；manifest 变化才重试 |
| **E2E 失败成本** | 失败 spec 63–64 s（2 条用例 × 30 s 测试超时） | 功能 E2E 与独立验收的生成提示词要求 `waitForResponse`/路由/关键断言使用 5–8 s 显式超时，缺失请求快速失败，30 s 仅作兜底 |

### 2.6 第六轮：全局壳（Application Shell）

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **壳被当成某一页的内容** | 产物把 `UI-header` 挂在 `UI-home` 下，导致导航只出现在部分页面；外部 `go('Books')` 要求每页都有 `navigation` 地与 `Books` 链接，9/12 用例在第一步超时。根因是设计逐需求进行、缺少应用级视图 | 元素新增 `scope`（`global`/`page`）：壳元素 `parent=null`、跨需求复用、子元素继承 global、页面不得复制主导航；设计提示词新增 `APPLICATION SHELL` 段，请求始终附带当前壳；`page_context` 把壳放在独立的 `shell` 键（页面子树不再包含壳）；实现提示词要求 `task.page.shell` 在应用入口渲染一次并包裹所有路由；`semantic_issues` 报告"global 元素嵌进页面""多页面无壳" |

### 2.5 第五轮：给 UI 设计 IR 增加可访问性语义

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **语义缺口** | IR 只有 `type`，没有 role/name；实现按"看起来像什么"选标签，于是"会跳转的编辑动作"被写成 `<a>`。外部测试按 `getByRole(button, {name:'Edit'})` 定位，整条流程失败；内部测试只用 `data-testid`，完全发现不了 | 设计提示词新增通用 `ACCESSIBILITY CONTRACT`：按**行为**而不是去向判定角色——改变数据/当前记录、提交、保存、取消、确认、删除、新增、打开编辑器或对话框 → `role: button`（即使同时改路由）；只在阅读流里切换视图（导航、面包屑、记录列表条目）→ `role: link`，其容器 → `role: navigation`；记录集合 → 带名字的 `region`；表单输入按可见标签命名。元素新增 `role`（必填）与 `name`（仅当可访问名≠可见文字）。规范化从 `type`/`input_type` 派生缺失角色，显式 role 为 button/link 时纠正同轴的 type；`semantic_issues()` 报告冲突与缺名，设计结束打印 role 分布 |
| **泛用性** | 规则不能写死某个任务 | 规则段不含任何业务词汇（测试断言规则段内不出现 book/shelf/stack 等词），只描述控件行为与可访问性语义 |

### 2.4 第四轮：D1 — Obligation 账本

| 项 | 问题 | 改动 |
| --- | --- | --- |
| **义务散落** | 字段级 R/W 在 `db_obligations`、API 设计、trigger 设计、三份验收报告里各存一半，无法回答"这条数据义务履行了吗"，`Resolved(Ω)` 只能人肉推断 | 新增 `infrastructure/shared/obligations.py`：把 6 份 artifact 投影成 `.arc/obligations.json`，每条记录带稳定的 `OBL-xxxxxxxx` ID、需求/步骤归属、`api`/`trigger` 分配者、`Inferred → Allocated → Verified → Implemented` 状态与测试证据；`Compiler._run` 每次 pass 后重建，摘要写入 `compilation.json` 并打印在收尾面板 |
| **不改门禁** | — | 纯投影：不改变任何 pass 的通过/失败、提示词或 IR；刷新失败只打印 `[OBLIGATIONS] ledger refresh skipped`，不影响编译 |

测试现状：`316 tests, OK (skipped=49)`。其中 46 条为 legacy 门控，2 条为环境门控
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
| 义务账本 | `.arc/obligations.json` 汇总每条数据义务的归属、分配者、生命周期状态与验收证据，摘要写入 `compilation.json` |
| 语义契约 | `ui_design.json` 的每个元素声明 `role`（必填）与 `name`（可访问名不同于可见文字时才声明）；实现阶段按 role 渲染，设计结束时打印 role 分布与冲突告警 |
| 应用壳 | 元素声明 `scope`（`global` = 跨页共享的 header/导航/footer，`page` = 页面内容）；壳只设计一次、跨需求复用，页面子树不含壳，实现阶段在应用入口渲染一次并包裹所有路由 |

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
- 全部单元测试：`230 tests, OK (skipped=48)`，与改动前基线逐条对比 **0 回归**。
- 模拟平台调用：用官方模板冒充注入基线执行 00 阶段，基线被完整移入备份目录，
  生成的 `backend/package.json` 为 `@arc/backend`，`deploy.sh` 通过 `bash -n`。
- 本地无平台环境时：`ROOT`/`REQ` 树写入 7 张 traceability 表，`interfaces` / `tests` 表记录
  API/页面/trigger 契约与各类测试；`runner-events.jsonl` 记录 `runner_state` / `requirement_state`，
  缺失图片只产生 warning。
- **E2E 复用已用真实产物本地复现验证**：冷启动 4.27 s → 复用 3.05 s（同一条 spec、同为 2 passed），强制回退 5.03 s，三次输出均可解析且无任何 [e2e] 行。
- **全局壳已落地**：旧产物在新规则下会报"several pages share no global shell"，说明壳缺口可被设计阶段识别；
  `tests/test_ui_shell.py` 18 条覆盖 scope 继承、壳投影、页面/壳分离与提示词通用性。
- **导航守卫验证通过**：bookstack 外部在守卫 + M1/M2 后达到 **12/12**（keep 待复跑），
  `semantic_issues` 能点名失败产物里的 3 个面包屑 navigation 地标。
- **M1/M2 已落地**：模板依赖全部精确版本；安装失败带 npm 尾部且同一 manifest 不重试；
  E2E 生成提示词加入 5–8 s 等待预算（`tests/test_dependencies.py`、`tests/test_wait_budget.py`）。
- **语义 IR 已落地**：旧产物规范化后得到 button=12/link=9/navigation=0 的分布，印证"规范化只是兜底，
  语义要靠新提示词重新设计"；`tests/test_ui_semantics.py` 18 条覆盖派生、纠正、告警与提示词规则。
- **义务账本在真实产物上自洽**：用仓库内 `output/demo/.arc` 实跑得到 59 条义务 / 3 个需求，
  全部 `Implemented`、`resolved=true`（该目录缺少 trigger 产物，因此只有 `api` 分配者）。
- **两次正式任务运行已对比**（同一任务，11 需求 / 8 API / 9 页面）：第一版 4795 s、外部测试 3/12；
  含 E2E 复用的版本 10782 s、外部测试 4/12。增量中约 4.7 ks 来自"复用从未成功、每次空等 180 s"的
  路径 bug（已修复并补回归测试），约 1.0 ks 来自服务端单次延迟翻倍（调用数反而更少）；
  读取拒绝 27→0、拒绝轮次 43→21、内部冒烟从部分失败转为全绿。
- **Smoke Competition 已完成一次端到端运行**（第一轮提交的代码），13/13 pass 完成、
  23/23 后端测试通过、UI 与端到端全绿；日志显示 98 次模型调用、输入 1.32M tokens
  （其中 63% 命中缓存）、输出 186k tokens，总耗时约 34.5 分钟。第 12 阶段占 47% 时间，
  其中大半是 E2E 反复起服务；依赖安装只额外发生 3 次、每次 8 秒（首次 42 秒），
  Chromium 只真正安装一次——**证实跳过 M8 是合理的**。

**已知限制**

- 46 条 legacy 用例尚未移植到当前契约（默认跳过，`ARC_LEGACY_TESTS=1` 可运行）。
- 契约与测试明细只覆盖到"一次运行"：重跑同一任务会覆盖行而不保留历史（历史由 Git 提交承担）。
- 依赖安装仍在 05/08/10/12 触发多次、Chromium 最多装 2 次：冒烟日志显示它们是增量（8 秒），
  保持现状；真正的大头（E2E 重复起服务）已改为复用。
- 复用服务器依赖"后端源码指纹 + 健康检查"判断；若平台容器禁止长驻进程，运行时会自动回退到旧行为。
- 只支持 web 任务；`cli` / `android` 会明确失败而不是给出错误结果。

---

## 6. 下一步

完整路线图、两次运行的日志分析、助教 14 个扩展点清单与三人分工见 **`ROADMAP.md`**。近期顺序：

1. **批次 1（M1+M2）**：锁定模板依赖版本并让安装失败一次即停、可诊断；E2E 等待预算降到 5–8 s。
2. **批次 2（M3+M4）**：后端路由 / 前端接线的静态完整性检查；IR 补齐 `status`/`aria-*` 状态与动态 name，
   语义告警进入一次修复回合。
3. **批次 3（M5+M6）**：种子幂等与测试知识注入；页面/路由骨架先行。
4. **批次 4（M7）**：RAG 始终携带应用壳与全部页面，"壳先行"设计。
5. **研究轨道**：D2 实际访问校验、D3 Reference 传播、D7 `correctness.json`，以及助教扩展点实验
   （01C 视觉、02C/06A 检索、03A/03C 义务推断、05A/05C SQL 下沉、06B API→DB 分解）。

> 历史：D1 义务账本（`533e04e`）、语义 IR（`4672e4d`）、全局壳（`66a5900`）、E2E 复用与静默
> （`9e0d778`→`4e91345`）已完成；内部测试的 role/name 断言暂缓到 M4 之后。
