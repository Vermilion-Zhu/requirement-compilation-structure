# 轻量网站 Agent 阶段交接

更新于 2026-11-15。用户继续整理实验分支的 README、版本和送测候选包。

## 开发位置和交付目标

最终交付是 ArcBench Agent 源码 ZIP。平台输入任意网站需求，框架自动生成应用和测试。
用户强调少修改、正确完成、跨任务适用，以及分钟级反馈。测试期望须来自源需求。

- 当前开发目录为 E:/D-download/se/team-requirement-compiler-react，分支 experiment/react-lite。
- 旧框架目录为 E:/D-download/se/team-requirement-compiler，分支 chore/agent-cleanup，39eae6b。
- 两个 worktree 共享 Git 对象和远程配置，源码工作区独立。
- upstream 为 https://github.com/Vermilion-Zhu/requirement-compilation-structure.git。
- origin 仍保存旧 fork，推送显式使用 upstream。
- 新实验用当前目录的 output。早期实验和预算脚本保留在旧目录的 output/react-experiment。
- Python 为 E:/D-download/se/lab6/leader-framework/.venv/Scripts/python.exe。
- 设置 PYTHONPATH 为当前开发目录。TEMP/TMP 使用 output/merge-check/tmp。
- 已有 Playwright CLI 为 E:/D-download/se/lab5/validation/bookstack-home-output/node_modules/@playwright/test/cli.js。
- 本地浏览器使用 channel=chrome。Linux、平台 Chromium 和云端运行仍待验证。

源码入口默认 staged。scripts/package.py --engine react 生成的包通过 agent-release.json
选择轻量引擎。送测包按 output/releases/用途 YYYYMMDD dzs.zip 命名，当前为 Lightweight ReAct 20261115 dzs.zip。
末节记录发布规则和验证结果位置。26fb48d 与 671be45 包供历史对照。

## 框架当前状态

requirements.py 保留完整源文档、未知字段、引用与指纹，角色声明只做部分词法索引。
runner.py 使用单个追加式 ReAct 会话，执行文件、进程、图像和 verify 工具。
submission.py 当前默认生成分批 typed plan，再编译固定 Playwright 后端、冻结、收集和执行。
分批仅收窄 implementation_ids，保留完整原始契约和 UI 上下文，以提供跨需求前置流程。
恢复会话先由控制器验收，有冻结测试时空 actions 也触发实际验证。

现有 acceptance.py 可以直接生成普通 Playwright TypeScript。本轮增加可选 implementation_ids，
沿用完整上下文，并在调用模型前拒绝空、重复和未知 ID。输出 case 越界会在写入前被拒绝。
增加通用提示，明确本批输出范围，以及动态 status 内容应依据原文。
这条普通 Playwright 路径仍处于实验阶段，尚未替换送测默认流程。

固定 typed 后端每例启动独立应用和数据库。普通 Playwright 实验共享一轮新服务，
浏览器身份使用独立 context，数据通过唯一值和 UI 前置流程隔离。比较时须记录此差异。
测试文件和清单有指纹校验。引用存在和用例收集通过，仍需继续检查逐条语义覆盖。

尚未集成按需测试切片、实现文件冻结、上下文压缩和七区域平台追溯。
工具路径检查无法代替操作系统沙箱。

## Git 检查点

- 513b5fa，首个轻量 ReAct 原型。
- 671be45，自动 typed tests、隔离、运行指纹和送测入口。
- 1985aac，分批测试和显式表单标签约定。
- 2a7a00c，完整分批上下文和恢复前验收。
- 9119d9f，保留 StackOverflow 首轮失败证据。
- ef9bc33，唯一邮箱保形，支持 ${unique} 位置模板。
- bce96bd，记录邮箱和动态状态断言缺陷。
- e4dc952，删除 visible 对 status 文字的隐式等值要求，保留显式内容断言，兼容旧 step-level within 并拒绝冲突/未知选项。

继续时用 git log 和 git status 核对本说明之后的提交。

## 输入和已验证结果

源包为 D:/download/se/arcbench-arc-bench-lite-requirements.zip，E: 有同名副本。
75 个文件已展开至 E:/D-download/se/arcbench-requirements-lite，指纹在 .source-archive.json。
Keep 为 6 项需求/11 场景，BookStack Lite 为 8/12，StackOverflow 为 17/27，
PrestaShop 为 19/32，12306 为 31/49，Ctrip 为 32/50。后三项尚未真实模型生成。

| 实验 | 耗时和状态 | 自动测试 | 外部测试 |
| --- | --- | --- | --- |
| Keep v6-auto | 225.7 秒，应用阶段 148.5 秒 | 11/11 | 11/11 |
| BookStack Lite v3-auto 首轮 | 369.6 秒，应用阶段 330.1 秒 | 12/12 | 10/12 |
| BookStack Lite 恢复修复 | 153.4 秒，3 次模型请求 | 12/12 | 12/12 |
| StackOverflow 首轮 | 总时限 900 秒，TIME_LIMIT | 27 例编译完成，应用未完成验收 | 尚无外部套件 |
| StackOverflow status-v3 修复后检查 | 修复运行 TIME_LIMIT，检查独立执行 | 20 通过、1 失败、6 未执行 | 尚无外部套件 |

BookStack 恢复修复已暴露外部测试，不能视为首次未见测试成绩。预填 textarea 的隐式
label 在本地 Chrome 下存在 exact getByLabel 兼容差异，显式 htmlFor/id 修复后通过。
外部套件保存在 arcbench-local-replay/imports。Keep 套件独立来源尚未进一步核实。
BookStack Lite 的 12 场景与完整任务 35 场景分别记录。

StackOverflow 原测试唯一值追加破坏邮箱格式，模型随后放宽应用校验，失败样本已保留。
后端还把 Title character count 的 accessible name 当成可见正文，错误拒绝数值状态。
修复后 status-v3 校准计划手动补了一条长度断言，属于人工校准，旧冻结版本继续保留。
修复运行 9 个循环约 361.6 秒，TIME_LIMIT。之后真实检查为 20/1/6，失败源于测试
把父问题和答案的 Score 混为全页唯一字段，应先修测试。应用源码由模型修订。
旧计划中依赖隐式 status 文字断言的覆盖情况仍需复核。

## 普通 Playwright 可行性实验

独立需求复核记录在当前 output/react-experiment/stackoverflow-plan-independent-review。
复核只接收源需求和测试，无应用源码/运行结果。27 条发现的原文引用已逐字核对，
各条判断仍需审阅。已确认缺口包括声望增减、合法的隐藏或禁用替代、身份和 UI 前置流程。
Typed DSL 缺少基线捕获、相对计算和合法替代分支，继续添加操作码会扩大维护范围。
因此复用已有 acceptance.py 试验直接生成普通 Playwright。

- 全任务直接生成 v1 在 24,000 输出 token 截断，推理占 20,882，未得到可用套件。
- focused-v2 只选 REQ-3.6 和 REQ-4.2，reasoning=none，18.531 秒，2 例成功收集。
- v2 独立源文/代码复核确认声望读取缺少等待，以及父问题分数依赖 DOM 顺序。
- focused-v3 在约 19.468 秒生成并收集 2 例，修正了声望轮询，但通过原始 aria-label
  识别答案。最小浏览器校准中 aria-label 命名通过，aria-labelledby 命名失败。
- focused-v4 超范围生成其他需求，被 case 校验拒绝，未写入可执行套件。
  原始结果位于旧实验根 focused-v4-rejected-proposal.json，调用原始响应也已保存。
- 本批两次修订已结束。没有把这些候选测试交给应用 Agent 修复，也没有新的应用通过率。
- 小范围、reasoning=none 和额外反馈同时变化，18 秒结果尚无法用于格式速度的因果比较。

v3 脚本首次读错前一版目录，在模型调用前退出，已纠正。校准首次缺 PYTHONPATH，
补齐后实际执行。框架测试首次用了不适用的模块导入命令，已改 discover 完整重跑。

关键实验文件位于当前 worktree 的 output。

- stackoverflow-v3-postrepair-check.json，20/1/6 检查。
- stackoverflow-playwright-focused-v2-summary.json 和 focused-v3-summary.json。
- react-experiment/stackoverflow-playwright-focused-v2-review/review.json。
- score-scope-calibration-summary.json，两种命名的实际浏览器校准，1 通过/1 失败。
- stackoverflow-playwright-focused-v4-generation.log，越界拒绝日志。
- react-resume-framework-tests.log、react-resume-plan-tests.log 和 react-resume-plan-live-tests.log。

## 模型授权和累计预算

用户授权通过现有 DEEPSEEK_API_KEY 向官方接口发送需求、提示、参考图及应用源码，
本阶段累计费用不超过人民币 5 元。所有实验复用旧目录 output/react-experiment 下的
api_budget.py 和 deepseek-budget-5cny.json。禁止重置账本或并发运行付费进程。

截至本轮 91 次调用，账本估算 0.226200828 美元。预算守卫累计上限 0.60 美元，
请求前按高峰未缓存价格和最多 24,000 输出 token 预留，成功后按 usage 更新。
失败保留预留。辅助预算文件位于 ignored output。后续模型原始响应保存于 deepseek-responses。
价格依据 https://api-docs.deepseek.com/quick_start/pricing/ 。

设置 OPENAI_API_KEY 为进程现有 DEEPSEEK_API_KEY，OPENAI_BASE_URL=https://api.deepseek.com，
MODEL=deepseek-flash，按试验明确指定 MODEL_REASONING。图像调用同样设置官方配置。
当前 worktree 无 .env。旧 .env 中平台额度已耗尽，不要复用。不要打印密钥。
子应用和工具进程会清除 OPENAI_API_KEY、VISUAL_API_KEY、DEEPSEEK_API_KEY。

## 后续优先级

1. 先解决测试输出范围和对象归属的一般约束，再进行下一批候选生成。
2. 将普通 Playwright 与 typed plan 在相同需求、推理档位、预算和隔离条件下对照，
   同时检查漏断言和误拒合法实现。保留失败样本，限制复核/修订次数。
3. 根据证据决定是否减少 typed DSL。避免为每个网站增加专用操作码或手写正式用例。
4. 保留自动生成后真正执行的检查，继续测试其他 Lite 项目的可迁移性。
5. 通过后重新打包，验证固定入口、文件指纹、凭据排除及平台运行环境。

Windows Chrome 本地测试无法验证 Linux 部署。WSL E 盘挂载曾报 E_ACCESSDENIED，
Docker daemon 当前不可用，环境修复未纳入此任务。

## 本轮回归检查

53 项框架和入口测试通过，日志为 output/react-resume-framework-tests.log。
后端 18 项离线检查通过，其中 4 项实时浏览器检查默认跳过。
启用浏览器后的首轮有 7 个子项失败，均报告外层 CHECK_TIMEOUT，涉及 2 个测试方法。
本地辅助脚本将外层进程期限从 45 秒增至 120 秒，保留原业务断言和 Playwright
用例期限，重跑这 2 个方法通过。实际含 9 个浏览器场景检查，见
output/react-resume-browser-deadline-retry.log。生产期限未作调整。
原首轮日志 output/react-resume-plan-live-tests.log 保留。预算守卫离线检查通过。

用户需求 ZIP 包含 6 份 requirements.yaml 和 69 张参考图。文字验收场景嵌在 YAML
的 scenarios/Given/When/Then 中。当前 Playwright 文件由测试编译器生成。
.source-archive.json 是本地展开时追加的指纹文件。外部回放测试来自单独保存的目录。

## 2026-11-15 后续核验与候选包

本轮没有修改正式执行代码。分批范围修正后的 native v5 在 20.922 秒生成两例并收集，
TypeScript 检查检出 HELPEFUL_USER 导入拼写错误。独立复核的 4 条发现中一条原文
引用校验失败，一条内容重复。人工接受前两条有效发现后只做了一轮修正。
v6 在 17.5 秒生成两例，收集及 TypeScript 检查通过。父问题分数仍用 DOM 顺序，
合法嵌套/同级布局四例校准为 2 通过/2 失败。已有应用对照为 1 通过/1 失败，失败在
答案 Author 区域。原文对答案 Author 的具体 role 不够明确，该失败归因保留待定。
应用未接收这些候选测试的修复指令。

原 status-v3 冻结测试以 maxFailures=0 跑完，结果 21 通过、6 失败、0 跳过，
Playwright 约 240.7 秒。三个失败来自全页同名标题或 Score 定位。一个评论导航用例
把 Questions feed 的 button 声明用于 Search results 的 link。两个评论用例在
Question post 内找不到 Add a comment，应用将 Comments 放在其同级，而 REQ-5.2
明确规定 within Question post。两例的前置创建身份另有遗漏，仍需同时复核。
这次检查未修改应用，原先 20/1/6 的记录保留。结果在
output/stackoverflow-status-v3-all-cases-check.json。

完整需求载荷审计在 output/react-contract-payload-audit.json。UI 索引占输入约
10–22%，完整原始条款占多数。该审计没有裁剪运行上下文。

新候选源码包为当前目录 output/releases/compiler-react-26fb48d-20261115.zip。
473,209 字节，SHA256 为 964461554cf7cace9a0c13516627f9bf950044cb8a2af79e0fccd4896cddab2d。
源码提交 26fb48dd98eec718fe19772178a5eb4c07dc1d86，打包时工作区干净，engine=react。
205 个文件指纹、路径边界、凭据和输出排除检查通过。解压入口默认选 react，
编译器调用使用 mock 验证接线。解压框架对已有 Keep 应用真实构建并跑过外部 11/11。
该检查零模型调用，属于已有应用回归。验证记录为
output/react-26fb48d-release-validation.json 和 output/react-26fb48d-export-control.json。
已有 test_package_release.py 一项通过。包内源码尚未通过 Linux/Chromium 云端实测。

累计账本 94 次调用、估算 0.240728088 美元，沿用原 5 元授权和 0.60 美元守卫上限。
本轮付费和浏览器检查进程均已结束。后续可从当前初步原型继续做跨任务推广。

## 0.1.0a1 发布整理

用户要求整理实验分支 README、解释框架思想与相对原框架的细节和成效，并提供送测包。
README 已改为中文分支说明，含架构图、十三阶段职责映射、模块位置、逐版变化、
真实结果、失败归因、运行命令和后续优化事项。

正式发布版本复用 pyproject.toml 的 project.version，首个编号为 0.1.0a1，
uv.lock 的本地项目版本同步。scripts/package.py 自动将版本写入 agent-release.json。
Git 标签采用 react-v0.1.0a1。用户指定送测 ZIP 使用 用途 YYYYMMDD dzs.zip，当前为 Lightweight ReAct 20261115 dzs.zip。
历史实验目录继续沿用原命名，源码用 Git 提交和内容指纹定位。

本轮执行逻辑的变化集中在发布清单版本字段，网站生成引擎使用当前 typed-plan 流程。
本轮 53 项框架/入口回归和 2 项打包回归日志分别在
output/release-0.1.0a1-framework-tests.log 与 output/release-0.1.0a1-package-tests.log。
实际发布 ZIP、SHA256、清单和导出入口核对结果写入
output/releases/react-0.1.0a1-validation.json。平台 Linux/Chromium 实测待补充。
