# 需求编译智能体：分析记录与改进路线图

> 共享入口文档。`docs/` 下的详细变更记录不对仓库可见（被 `.gitignore` 排除），
> 本文件是组内唯一需要同步的规划与结论汇总。
> 每次提交运行后：更新 §1 指标、在 §10 追加一条运行记录、勾选 §6 的验收项。

## 1. 当前基线

| 指标 | bookstack（semantics_enhanced） | keep（semantics_keep） |
| --- | --- | --- |
| 总耗时 | 5037 s | 4256 s |
| 模型时间 | 4114 s（82%） | 2818 s（66%） |
| 模型调用 | 212 | 195 |
| 失败检查 | 7 后端 + 9 UI + 9 E2E = 25 | 8 后端 + 2 UI + 8 E2E = 18 |
| 调用最多的阶段 | 12=82、08=50、10=22 | 08=68、12=56、05=21 |
| 最慢阶段 | 12=2357 s、10=1168 s | 05=762 s、12=1506 s、08=598 s |
| E2E | 27 次 / 9 失败 / 315 s | 22 次 / 8 失败 / 296 s |
| 最终状态 | 13/13 DONE，冒烟 GREEN | 13/13 DONE，冒烟 GREEN |
| 外部测试 | **12/12**（2026-11-11，导航守卫修复后） | **8/11**（待复跑） |
| 读取拒绝 | 0 | 0 |
| 壳 / 语义 | `7 global elements`，navigation=1 | `4 global elements`，navigation=1 |

最近两轮（`breadcrumb_fixed_*`，M4 重放前）：

| 任务 | 外部 | 总耗时 | 内部状态 | 关键问题 |
| --- | --- | --- | --- | --- |
| keep | 8/11 | 4798 s | 13/13 DONE，冒烟 GREEN | 设计仍是 `alert`、无 `state`；status / `aria-pressed` 缺口未消 |
| stackoverflow | 9/27 | 19068 s | 13/13 DONE，内部全 GREEN | 入口 `/` 无 Question feed、导航名/角色不符；18 条失败全为 10 s 超时 |

已交付能力（对应提交）：E2E 服务器复用与静默（`9e0d778`→`4e91345`）、
义务账本 D1（`533e04e`）、语义 IR role/name（`4672e4d`）、全局壳（`66a5900`）。

## 2. 决策记录

| 决策 | 结论 |
| --- | --- |
| 模板 | 保留自研 react-express-sqlite 模板，不换官方 JS baseline |
| `max_turns` | 保持 20（正确率优先；两次运行最大轮次 3/6/12，未触顶） |
| M8 预算 | 不调（安装是增量的，Chromium 只装一次） |
| 内部测试断言 | 暂不升级为 role/name 断言（本轮只做 IR 与壳） |
| 语义校验 | 先告警（`semantic_issues`），本路线图 M4 再升级为一次修复回合 |
| 依赖版本 | 待锁定（M1）；当前 `^4.0.0` 浮动导致过 ETARGET |

## 3. 两次运行的共同根因（按代价排序）

### C1 数据接线缺失只在运行期暴露（最大问题）

- 阶段 12 的唯一失败诊断里，bookstack 8/15、keep 5/18 条都是"页面只改本地 state，从不发 API 请求"。
- 根因：pass 10 明确把数据加载推迟到 12（`ui/implementation.py:74-75`），12 又逐需求重写，
  唯一信号是 E2E 30 s 超时（失败 spec 63.1 s / 64.2 s = 2 条用例 × 30 s）。
- 代价：阶段 12 占 47% / 35% 墙钟；E2E 失败 9 / 8 次。

### C2 后端路由注册不完整（阶段 08）

- bookstack：`POST /api/books/:bookId/pages` 缺失 → 404。
- keep：`GET/POST /api/notes`、`PATCH /api/notes/:id/pinned` 缺失 → 404。
- 代价：阶段 08 50/68 次调用、7/8 次失败；只能由 HTTP 测试反推。

### C3 增量页面装配留下占位路由 / testid 漂移（阶段 10）

- bookstack：`/books/:id/edit` 复用 `UI-book-form*`；`/pages/new` 落到 `PlaceholderPage`；
  `page_edit` 复用 `page_form` 的 presentationData id → 9 次 UI 失败、22 次调用、1168 s。
- keep 页面少（2 页），只暴露 2 次失败，但机制相同。
- 附带：UI 存在性套件使用空展示值（`ui/testing.py:44`），标题/段落无高度被判 hidden（bookstack 9 次）。

### C4 种子与 fixture 假设导致过度约束

- bookstack：fixture 重跑 `initializeDatabase`，`Book.sql` 只按 title 幂等 → `UNIQUE constraint failed: Book.id`；
  测试假设表名字面叫 `books`。
- keep：种子笔记 `Meeting agenda 2.8.1` 混入断言，strict mode 匹配到两条；测试假设只有自己的行。
- 代价：两次共 3 条 `test_overconstraint` + 1 条 `test_requirement_mismatch` 诊断与修复轮次。

### C5 依赖安装不可复现且不可诊断（keep 的 762 s）

- `templates/frontend/package.json` 里 `tailwindcss: "^4.0.0"`、`@tailwindcss/vite: "^4.0.0"`；
  平台镜像缺 `@tailwindcss/oxide@4.3.5` → **6 次 ETARGET、5 次安装失败、10 次 install、12 轮编辑**。
- 失败信息只有 "see the npm output above"（`shared/project/dependencies.py:40`），代理看不到输出。
- `database/implementation.py:178-180` 的 `manifest` 只在安装成功后才赋值 → 失败后每轮重试。

### C6 IR 没有承接需求里显式写出的 ARIA 角色与状态

- keep 需求原文：`"Note archived"(role=status)`、`Unpin {title} exposes pressed=true`、
  `aria-current=true`、`aria-expanded=true`。
- 设计产出：两个通知是 `role=alert`；pin/unpin/toggle 没有任何 `aria-*` 状态字段。
- 根因之一是我们的提示词：`ui/design.py:67-68` 写"Status and error messages are role alert"，
  通用规则覆盖了显式需求（`L74` 虽写"需求 role 优先"，但没有写进同一段）。
- 设计结束还报了 3 条 `region needs an accessible name` 警告，但只打印不修复。

## 4. 外部测试差距（keep 8/11）

`docs/keep_tests.txt` 的 11 条用例中，最可能失败的 3 条恰好落在 C6：

| 用例 | 依赖的契约 | 设计记录 |
| --- | --- | --- |
| REQ-1.1 打开工作区（`keep_tests.txt:4-13`） | `aria-expanded`、`aria-current` | 无状态字段 |
| REQ-2.4 归档/撤销（`keep_tests.txt:65-117`） | `getByRole('status')` | `role=alert` |
| REQ-2.5 pin/unpin（`keep_tests.txt:118-159`） | `aria-pressed` | 无状态字段 |

结论：**需求里写清楚了，是 IR/提示词在传递中丢掉了**。补齐 `state`/`aria` 与显式 role 传递后，
这类任务应能到 11/11；具体失败清单仍建议向平台确认后回填本节。

## 4b. 入口路由与导航契约缺口（2026-11-13 stackoverflow）

**现象**：外部 9/27；18 条失败全部是 `Test timeout of 10000ms exceeded`，且都从 `entry` / `login` /
`mainNav` 开始。内部 backend 85/85、UI 28/28、E2E 25/25 全绿。

**本地复现**（构建产物 + 起服务 + Playwright 探针）：

| 检查 | 结果 |
| --- | --- |
| `/questions` | `Question feed`、`Ask Question`、题目按钮都在 |
| `/login` → 提交 `stack_user` | 登录成功，banner 显示 `Stack User` |
| `/` 与登录后的跳转 | 只有 `<h1>Home</h1>`，**没有 Question feed** |
| 导航 | 有一个 `navigation`，名字是 `Primary navigation`；子项是 `<a>` 链接 |
| 需求 | "reload the returned homepage … Question feed appears"；"Follow Questions in Main navigation" |

**根因**：

1. **入口路由没有建模**：设计只有 8 个页面（`/questions`、`/login`、…），没有 route `/`；
   实现里留了一个内联占位 `HomePage`。外部 `entry` / `login` helper 在 `/` 等 Question feed，
   于是 18 条用例全部 10 s 超时。内部存在性测试只覆盖设计页面，所以全绿。
2. **命名地标不保真**：需求写 "Main navigation"，设计与应用用 "Primary navigation"，按名字定位会落空。
3. **导航项角色与外部契约相反**：外部 `action(mainNav(page),'Questions')` 按 button 找；应用渲染的是链接。
   书栈任务的需求明确写 "Books link in navigation"（link 正确），stackoverflow 写 "Follow Questions…"（button），
   说明角色必须由需求措辞决定，不能一律按 link。

**结论**：这是一个可泛化的缺口——"应用入口路由"和"需求里命名的地标/角色"没有进入设计与验收；
补上"入口页 + 命名地标保真 + 提交前语义探针"可以同时覆盖这两个任务类别。

## 5. 助教扩展点（`infrastructure/stages/passes/`，共 14 处）

| 编号 | 位置 | 助教提示（摘要） | 与我们的关系 | 优先级 |
| --- | --- | --- | --- | --- |
| 01A | explore_requirement.py:269 | 尝试其他需求源格式/更强语法校验；保留 ID、包含关系、场景与步骤原文 | 输入健壮性 | P3 |
| 01B | explore_requirement.py:285 | 扩展参考文档发现；保持相对路径；先发布快照 | 输入健壮性 | P3 |
| 01C | explore_requirement.py:303 | 重写 `shared/models/vision.py` 的视觉抽取策略，保留 `{layout,elements,style}` | 视觉→语义（角色/标签）可做实验 | P2 |
| 02A | build_db_schema.py:18 | 实体边界、复用、约束推断实验 | DB 正确性，当前非瓶颈 | P3 |
| 02B | build_db_schema.py:88 | 调整遍历顺序或节点上下文 | 与"应用级视图"相关 | P3 |
| 02C | build_db_schema.py:109 | 检索/RAG：BM25、embedding、混合、重排 | **M7 直接相关** | P1 |
| 02D | build_db_schema.py:123 | 生成证据与 JSON 解析纠错策略 | 与 M1/M3 的反馈质量同源 | P2 |
| 03A | infer_db_obligations.py:19 | 改写需求→读写映射（失败路径、fixture、生成键） | 影响 API/UI 覆盖与测试 | P2 |
| 03C | infer_db_obligations.py:94 | 一次调用推断需求+步骤，可拆分或加证据 | 推断质量 | P3 |
| 05A | implement_db.py:20 | SQL 下沉策略 | DB 正确性 | P3 |
| 05B | implement_db.py:64 | 依赖顺序、循环外键 | 已实现，验证为主 | P3 |
| 05C | implement_db.py:97 | 生成上下文与纠错 | 反馈质量 | P2 |
| 06A | design_backend_apis.py:140 | 叶子顺序与可复用 API 发现 | **M7 复用/检索相关** | P1 |
| 06B | design_backend_apis.py:214 | "Intentionally absent: API 直接访问数据库" | **M8 的 D2 方向** | P2 |

## 6. 里程碑计划（按批次顺序实现）

### 批次 1：先消除波动（低风险，1 天）✅ 2026-11-09 已完成，待下一次运行验证

#### M1 依赖安装可复现、可诊断 ✅

- **目标**：消除 ETARGET 类 762 s 浪费；安装失败一次即停、信息可读。
- **改动**：
  1. `templates/frontend/package.json` 锁定精确版本（选镜像实测可用的 tailwind 版本），随模板提供 lockfile；
  2. `install_dependencies` 收集输出尾部（最后 ~20 行）写进异常与代理反馈；
  3. `database/implementation.py` 的 gate 记住"已尝试的 manifest"（失败也记住），本 pass 内不重试；
  4. 安装前比较 manifest 摘要 + `node_modules` 关键依赖，未变化则跳过。
- **验收**：一次运行 `install_calls ≤ 4`、无 ETARGET、阶段 05 < 120 s。
- **已完成**：模板 tailwind 锁到已验证可用的 `4.3.4`；`install_dependencies` 失败信息带 npm 尾部；
  `ensure_database_dependencies` 同一 manifest 失败只报一次、不再重跑安装。
  单测：`tests/test_dependencies.py`（版本锁定、失败尾部、重试抑制）。
- **风险**：锁版本与镜像不一致 → 用两次安装验证后再定版本。
- **关联**：TA 02D/05C；轨道 A。

#### M2 E2E 等待预算 ✅

- **目标**：失败用例从 30 s 降到 5–8 s，减少阶段 12 墙钟与反馈延迟。
- **改动**：阶段 12 的测试生成提示词要求 `waitForResponse`/关键 locator 显式 5–8 s 超时；
  配置中仍保留 30 s 测试总超时兜底。
- **验收**：失败 spec ≤ 12 s；E2E 总时长下降 ≥ 30%。
- **已完成**：功能 E2E 与独立验收的生成提示词都要求 5–8 s 显式超时（`waitForResponse`/路由/断言），
  不再依赖 30 s 测试超时；单测：`tests/test_wait_budget.py`。
- **风险**：慢环境误报 → 8 s 起步，可调。
- **关联**：轨道 B。

### 批次 2：收益最大的两项（2–3 天，可并行）

#### M3 静态完整性门禁

- **目标**：把"缺路由/缺接线"从运行期 404 与 30 s 超时，前移为精确的静态反馈。
- **改动**：
  1. 阶段 08 每需求后：扫描注册文件（`backend/src/app.ts`/`register.ts`）对照
     `backend_apis.json` 的 method+path，缺失则列出清单；
  2. 阶段 12 每需求前：对 trigger 的 `action.api` 检查页面源码是否出现对应请求
     （fetch/axios + 路径/方法），缺失则批量反馈；
  3. 新模块 `infrastructure/shared/checks/wiring.py`，只报告不阻断起步，误报率稳定后再升级为门禁。
- **验收**：阶段 08 无 404 类诊断；阶段 12 无 "never calls API" 诊断；两阶段调用数各降 ≥ 30%。
- **风险**：动态 URL/封装请求造成误报 → 宽松匹配 + 白名单。
- **关联**：TA 06B、02D；轨道 A（后端）+ C（前端）。

#### M4 语义 IR 补齐（C6 的正面修复）✅ 2026-11-11 已重放（pre-m4 检查点之后）

- **目标**：需求里显式写出的 role/aria 状态不丢失。
- **改动**：
  1. 提示词：`status`（成功/提示）与 `alert`（错误/中断）分开；"需求显式 role 优先"写进
     ACCESSIBILITY CONTRACT 本身；
  2. IR：新增 `state`/`aria` 映射（`pressed`/`current`/`expanded`/`selected` + 变量），
     `name` 支持 `{var}` 模板（动态区域名）；
  3. `semantic_issues` 非空时进入一次修复回合（不再只打印）。
- **验收**：keep 类任务外部 11/11（若失败确在 status/pressed）；设计告警为 0；alert/status 分布正确。
- **重放**：在 `pre-m4` 检查点（`b92f2a1`，bookstack 12/12）之上重放 M4，保留导航守卫；
  合并点为 design/implementation 提示词与测试，全量 `289 tests, OK`；待新一轮运行验证 keep 外部成绩。
- **回退原因**：bookstack 外部 11/12 → 3/11。产物显示该轮把面包屑建模成 3 个页面级 `navigation` 地标，每个都含 "Books" 链接；外部 `go()` 的 `getByRole('navigation').filter(has link 'Books').getByRole('link', {name:'Books'})` 因此解析到 2 个元素（全局壳 + 面包屑），9 条用例 strict-mode 失败。语义字段本身不是直接原因，而是「面包屑是 navigation」这一既有提示词遇上外部定位假设；已先加导航地标守卫（见 §9），M4 待守卫验证后重放。
- **风险**：提示词影响其他任务 → 下一轮对比 bookstack + keep 两次运行。
- **关联**：TA 03A/03C；轨道 B。

### 批次 2.5：入口路由与语义前置校验（最高优先，2026-11-13 新增）

#### M8 入口路由建模（`/` homepage）

- **目标**：需求描述的"homepage / landing / feed"必须是设计中的一个真实页面（route `/`），
  不是实现里的占位 Home。
- **改动**：设计提示词要求"应用入口路由是一个页面；若需求说 homepage / Question feed appears，
  该页面承载主集合"；`semantic_issues` 增加"需求提到 homepage/feed 但设计没有 route `/`"；
  实现提示词禁止保留占位首页。
- **验收**：stackoverflow 的 `/` 渲染 Question feed；内部存在性测试覆盖 `/`；外部 `entry`/`login` 不再超时。

#### M9 命名地标与导航角色保真

- **目标**：需求里命名的地标（如 "Main navigation"）与角色描述（`"X"(role=button)`）必须原样进入 IR。
- **改动**：设计提示词强调地标名逐字保留；新增校验：从需求文本抽取 `"NAME"(role=ROLE)` 与
  `<name> navigation` 类命名，检查设计元素存在对应 name/role；导航项角色规则改为
  "需求称其为 link 才用 link；否则切换视图的导航项用 button"（书栈 "Books link" → link，
  stackoverflow "Follow Questions" → button）。
- **验收**：stackoverflow 导航名 = "Main navigation"、Questions 为 button；书栈仍为 link 且 12/12。

#### M10 提交前语义探针（preflight probe）

- **目标**：在提交前用真实浏览器验证"需求声明 + 壳 + 入口"这些内部测试看不到的契约。
- **改动**：新增脚本（可放 `scripts/`），从 requirements 抽取 `"X"(role=Y)`、地标名与入口页预期，
  对本地构建产物跑一次 Playwright 断言：入口路由内容、命名地标、角色、关键页面区域。
  失败即阻止提交并输出缺失清单。
- **验收**：能对 `breadcrumb_fixed_stackoverflow` 产物报出"`/` 无 Question feed、导航名不符、Questions 角色不符"；
  下一次提交前 0 失败。

### 批次 3：质量与装配（2 天）

#### M5 种子与测试知识

- **目标**：消除 `UNIQUE constraint`、种子串入断言、表名猜测。
- **改动**：种子 SQL 以主键幂等；fixture 只播种一次或测试按创建的 id/title 作用域；
  测试生成提示词注入规范表名与当前种子清单。
- **验收**：`UNIQUE constraint` 诊断 0；overconstraint/mismatch ≤ 1。
- **关联**：TA 03A；轨道 A（种子）+ C（测试生成）。

#### M6 页面/路由骨架先行

- **目标**：阶段 10 不再因占位路由/复用错 testid 反复失败。
- **改动**：逐页实现前，一次调用生成 App 路由 + 全部页面空组件 + testid 占位；之后逐页填充。
- **验收**：阶段 10 UI 失败 0；阶段 10 < 500 s。
- **风险**：多一次调用；已有文件需增量修改。
- **关联**：轨道 B。

### 批次 4：检索与整体视图（P2，可持续）

#### M7 RAG 应用级视图

- **目标**：设计阶段始终看到"壳 + 全部页面"，减少跨页不一致。
- **改动**：检索固定附带壳与页面清单；"壳先行"子阶段；用"同一壳元素被多页引用"作为一致性指标。
- **验收**：跨页壳缺失告警 0（已达成）；新增页面自动复用壳。
- **关联**：TA 02C、06A。

### 批次 5：研究轨道（与主流程解耦）

| 方向 | 内容 | 关联 |
| --- | --- | --- |
| D2 实际访问校验 | 声明 R/W 与生成代码的实际 SQL/查询比对 | TA 06B、principle.md |
| D3 Reference 传播 | data/state 两种语义 | principle.md |
| D7 correctness 报告 | 消费 obligations + wiring 检查，输出三层报告 | D1/D2 |
| 视觉→语义实验 | 01C：从参考图抽 role/label，补 IR | TA 01C、M4 |
| 检索实验 | 02C/06A：BM25 vs 混合 vs 重排 | TA 02C/06A |
| 义务推断实验 | 03A/03C：失败路径、fixture、粒度 | TA 03A/03C |
| SQL 下沉实验 | 05A/05C：DDL 生成与纠错 | TA 05A/05C |
| 内部断言升级 | 存在性测试断言 role/name（暂缓） | M4 后续 |

## 7. 分工建议（3 人）

| 轨道 | 负责内容 | 里程碑 | 依赖 |
| --- | --- | --- | --- |
| A 后端/数据 | 依赖与安装、后端路由检查、种子幂等 | M1、M3a、M5a | 无 |
| B 前端/IR | 语义 IR、页面骨架、E2E 预算 | M4、M6、M2 | 无 |
| C 流程/度量 | 前端接线检查、测试知识、RAG、每轮分析 | M3b、M5b、M7 | M3a 的检查框架 |

协作规则：

1. 每批次结束提交一次，并跑**同一任务**（bookstack 与 keep 至少各一次）做对比；
2. 分析脚本统一 `uv run python scripts/analyze_log.py docs/logs/<name>.log --json docs/logs/<name>.json`；
3. 外部套件本地重建（`docs/keep_tests.txt` 同构方式）作为每轮验收；
4. 改动按里程碑单独提交，提交信息写清关联编号（M1…M7），便于回滚与归因。

## 8. 度量协议

每轮提交后记录：

| 字段 | 来源 |
| --- | --- |
| 总耗时 / 模型时间 / 调用数 | `analyze_log.py` |
| 各阶段状态与耗时 | 同上 `stages` |
| 失败检查（backend/ui/e2e） | 同上 `checks.kinds.*.exits` |
| 阶段 08/12 的失败诊断类别 | 日志 JSON 诊断（cause/reason） |
| 安装次数 / ETARGET | 日志 `Installing dependencies` / `ETARGET` |
| 外部通过率 | 平台结果（贴到 §10） |

判定标准（目标值）：

- 阶段 08 无 404 诊断、调用数 < 30；
- 阶段 12 无 "never calls API" 诊断、调用数 < 40；
- 失败 E2E spec ≤ 12 s；
- 依赖安装 ≤ 4 次/run；
- 外部 keep ≥ 11/11，bookstack ≥ 9/12（逐步逼近）。

## 9. 已知问题与暂缓事项

| 项 | 状态 |
| --- | --- |
| D1 账本在无前端证据时过早 `RESOLVED`（第 11 阶段即 103/103） | 待修：`Implemented` 需要前端证据或明确"无 UI" |
| 壳上的交互（登录/退出等）未进入 trigger 设计 | 待设计：壳元素纳入 trigger 范围 |
| 面包屑被建模成第二个 navigation 地标（外部 strict mode 冲突） | ✅ 已修：提示词禁止第二地标 + `semantic_issues` 报告重复链接 |
| 入口路由 `/` 未建模，实现用占位 Home（stackoverflow 9/27 主因） | M8 |
| 命名地标/导航角色与需求不符（Primary vs Main navigation、link vs button） | M9 |
| 内部测试看不到入口/壳语义，提交前无保护 | M10 |
| 内部测试仍只断言 testid | 暂缓（M4 之后） |
| `install_dependencies` 失败重试 | ✅ M1 已修（同一 manifest 不重试） |
| 语义告警只打印不修复 | M4 |
| 动态 name（`{title}`）无法表达 | M4 |
| keep 的 3 条外部失败未与平台清单对照 | 待补 |

## 10. 运行记录（append-only）

### 2026-11-13 · stackoverflow（breadcrumb_fixed_stackoverflow）9/27

- 总 19068 s（5.3 h）、535 次模型调用；13/13 DONE；内部 backend 85/85、UI 28/28、E2E 25/25 全绿。
- 外部 9/27；18 条失败全部是 `Test timeout of 10000ms exceeded`，都从 `entry` / `login` / `mainNav` 开始。
- 本地探针：`/questions` 正常、登录成功；但 `/` 只有 "Home" 标题，无 Question feed；
  导航名 "Primary navigation"（需求 "Main navigation"），导航项为链接（外部按 button 取）。
- 设计没有 route `/` 页面，实现保留内联占位 HomePage；内部测试只覆盖设计页面，因此全绿。
- 阶段耗时：12=8460 s、08=3179 s、10=2033 s、11=1621 s；失败检查 19 后端 + 11 UI + 26 E2E。
- 结论：入口路由 + 导航名/角色是主因；先做 M8/M9/M10，再继续 M3/M5/M6。

### 2026-11-13 · keep（breadcrumb_fixed_keep）8/11

- 总 4798 s；阶段 11=1026 s、08=828 s、12=1528 s；7 后端 + 2 UI + 7 E2E 失败。
- 设计仍是 `alert=2`、0 个 state（M4 未重放），外部 8/11 与上次一致，缺口仍是 status / `aria-pressed`。
- 待 M4 重放后的下一轮复跑验证。


### 2026-11-06 · bookstack（semantics_enhanced）

- 总 5037 s；全阶段 DONE；冒烟 GREEN；外部较前两版提升。
- 主要问题：阶段 12 数据接线（8 条诊断）、阶段 10 占位路由/testid（9 次 UI 失败）、
  后端 create-page 路由缺失（404）。
- 结论：壳与 role/name 生效（navigation=1，7 个全局壳元素）。

### 2026-11-11 · bookstack 恢复 12/12

- 导航地标守卫（`8b4b5a0`）+ 重放 M1/M2（`661059c`）后，bookstack 外部 **12/12**；
  keep 仍在运行，待回填。
- 守卫在真实设计上的行为已验证：上一轮失败产物的 3 个面包屑地标会被 `semantic_issues` 全部点名。
- 记录一个回退点（tag `pre-m4`），随后重放 M4（状态/`status`/动态名称 + 一次修复回合）。
- M4 已重放：保留守卫，合并后全量 290 tests 通过；等新一轮 keep/bookstack 结果回填。

### 2026-11-09 · bookstack 回归（ir_amended）

- 外部从 11/12 跌到 3/11。本地重建外部套件复现 3/12：9 条用例在同一处失败
  `strict mode violation … resolved to 2 elements`（`UI-books-link` 与 `UI-book-breadcrumb-books`）。
- 设计产物含 3 个页面级 `navigation`（book / book-delete / page 面包屑），每个都有 "Books" 链接；
  上一版 11/12 的设计只有 `UI-app-nav`、没有面包屑元素。
- 处理：回退 M1/M2/M4（`f87c13b`）；新增导航地标守卫与提示词（`8b4b5a0`）；重放 M1/M2（`661059c`）。
  M4 暂不重放，待守卫在新一轮设计中生效后验证。

### 2026-11-08 · keep（semantics_keep）

- 总 4256 s；全阶段 DONE；冒烟 GREEN；**外部 8/11**。
- 主要问题：阶段 05 依赖安装循环（762 s、6 次 ETARGET、12 轮）；
  阶段 08 三个路由缺失；阶段 12 数据接线（5 条诊断）。
- 语义差距：通知 `alert` vs 需求 `status`；无 `aria-pressed`；3 条 region name 警告未闭环。
- 结论：壳生效（4 个全局元素，navigation=1）；外部失败集中在 ARIA 状态与 status。
