# 轻量网站 Agent 阶段交接

2026-11-15。用户因关机明确要求暂停，线程目标已标记为 paused。
本地模型测试进程已经结束。下一阶段开始前先阅读本说明和 REACT_EXPERIMENT.md。

## 目标和约束

最终交付物是上传 ArcBench 的 Agent 源码 ZIP。平台给定新的网站需求后，
Agent 自动编译测试、生成应用、执行验收和修复。重点包括需求语义保留、
独立测试、低延迟、低模型消耗。用户强调少修改、正确完成和跨任务适用。

人工编写的校准应用和测试计划用于验证框架后端。送测入口从公开需求生成测试。
源需求优先，默认解释只填补未明确的属性。对外报告须区分应用生成、测试编译、
人工校准、记录重放、外部测试，以及 Lite 与完整任务。

## 工作目录与 Git

两个 worktree 已在暂停前拆开。

| 目录 | 分支 | 框架状态 |
| --- | --- | --- |
| E:/D-download/se/team-requirement-compiler | chore/agent-cleanup | 旧框架，39eae6b |
| E:/D-download/se/team-requirement-compiler-react | experiment/react-lite | 轻量实验框架 |

两个目录共享 Git 对象和远程配置，各自维护源码工作区。后续开发使用第二个目录。
早期实验产物继续保存在旧目录的 output/react-experiment 下，完整绝对路径仍有效。

开发分支跟踪 upstream/experiment/react-lite。upstream 指向组长仓库
https://github.com/Vermilion-Zhu/requirement-compilation-structure.git 。
origin 仍保存旧 fork 地址，推送时显式使用 upstream。

主要检查点如下。

- 513b5fa，首个推送的 ReAct 原型，包括来源关联和独立验收。
- 671be45，已推送。自动测试计划、固定浏览器后端、每例隔离、运行指纹、送测入口和打包清单。
- 1985aac，暂停前新增。测试编译按场景规模分批，补充显式表单标签关联和首次浏览器检查使用 verify 的提示。
- 本交接说明通过后续文档提交保存，恢复时用 git log 核对最终 HEAD 和远程同步状态。

## 新的 Lite 输入包

用户指定 D:/download/se/arcbench-arc-bench-lite-requirements.zip。
同名文件在 E:/D-download/se 也存在。已将 75 个需求和图片文件展开至
E:/D-download/se/arcbench-requirements-lite，并写入 .source-archive.json 记录源包及文件指纹。

| 子任务 | 实现需求数 | 原始场景数 | 本地进度 |
| --- | --- | --- | --- |
| arc-bench-lite--keep | 6 | 11 | 与已测原输入的语义指纹相同 |
| arc-bench-lite--bookstack | 8 | 12 | 与已测原输入的语义指纹相同 |
| arc-bench-lite--stackoverflow | 17 | 27 | 尚未运行模型生成 |
| arc-bench-lite--prestashop | 19 | 32 | 尚未运行模型生成 |
| arc-bench-lite--12306 | 31 | 49 | 尚未运行模型生成 |
| arc-bench-lite--ctrip | 32 | 50 | 尚未运行模型生成 |

## 已有结果

旧实验根目录为 E:/D-download/se/team-requirement-compiler/output/react-experiment。

| 实验 | 总耗时 | 自动测试 | 另存外部测试 |
| --- | --- | --- | --- |
| keep-v6-auto | 225.7 秒，包含测试编译和收集 | 11/11 | 11/11 |
| bookstack-v3-auto 首轮 | 369.6 秒，包含工具准备和测试编译 | 12/12 | 10/12 |

Keep 应用阶段 148.5 秒、8 轮、3 次图片分析。BookStack 应用阶段
330.1 秒、18 轮、4 次图片分析。BookStack 的多轮时间花在自编 smoke 脚本定位上。
当前提示要求优先调用控制器 verify，再根据失败做局部诊断，效果仍需新一轮验证。

BookStack 的外部失败均在 REQ-2.4 编辑已有 metadata。
自编 smoke 曾在 getByLabel('Description', exact=true) 超时，Agent 将自己的
smoke 改为 getByRole 查询后通过。自动生成的独立测试同样使用 role 查询，
因而首轮自动验收通过，外部 label 查询仍失败。
页面在编辑时 textarea 已有值，嵌套隐式 label 的文本匹配是待最小复现的怀疑点。

1985aac 增加了通用 htmlFor/id 表单关联约定，随后尝试沿原会话修复。
这次修复以 STEP_LIMIT 结束，6 轮均返回空 actions，进度文字声称已经通过。
控制器报告保留了 STEP_LIMIT，实际没有进行本轮应用修改和重新验收。
BookStack 外部成绩继续按 10/12 记录。

首轮报告和会话保存在 bookstack-v3-auto/.arc/ 下的
react-report-before-label-repair.json、react-session-before-label-repair.json。
最新覆盖报告保留失败的修复尝试。修复日志位于新 worktree 的
output/bookstack-label-repair.log。

Keep 自动测试在准备好的正例应用上通过 11/11，也拒绝了旧 v1 应用。
v1 的首次失败发生在创建后的标题卡片定位，尚不能据此声称这次校准单独证明了 status 缺陷检测。

## 下一阶段优先处理

1. 修正分批上下文。目前 partition_contracts 只保留当前需求及祖先，可能丢掉跨需求的
   前置创建流程和引用。优先考虑每批保留完整原始契约，仅收窄 implementation_ids，
   这样可以减少依赖裁剪逻辑并复用公共输入前缀。为跨批前置条件增加回归测试。
2. 修正恢复会话的验收接线。已有完成历史让模型连续声称完成并返回空 actions。
   恢复到新的验收集合时，控制器应先实际验证当前应用并返回具体失败。
   增加空 actions 连续出现的回归测试，保留真实完成状态与费用边界。
3. 最小复现预填 textarea 的 label 查询问题。通过 Agent 的通用表单实现约定修复，
   再跑 BookStack 的自动测试和外部 12 例。保留现有冻结测试。
4. 用用户的新 Lite 包，从较小的 StackOverflow 或 PrestaShop 开始验证多批测试编译，
   然后根据剩余时间和费用测试 Ctrip、12306。每轮保留输入、提交、提示词及测试指纹。
5. 重新打包当前提交并验证固定入口。671be45 的候选包尚未包含 1985aac 的后续改动。

目前代码只校验需求 ID 覆盖、引用存在、计划格式、实际用例收集及测试完整性。
原始场景的逐条语义覆盖、合法替代实现、独立断言复核仍需加强。
按需执行测试切片、实现范围冻结、七区域平台追溯和上下文压缩也尚未集成。

## 模型费用与授权

用户允许复用系统环境变量 DEEPSEEK_API_KEY，向 DeepSeek 官方接口发送测试所需需求、
提示词、参考图和应用源码，并指定本次累计费用在人民币 5 元以内。
用户随后明确暂停，恢复后再继续模型实验。

截至暂停，账本记录 42 次调用，按已报告 usage 和当前周末费率估算
0.070563834 美元，按约 6.7 元/美元折算约 0.47 元。
账本包含失败的首次计划和空 actions 修复调用。

账本和执行辅助脚本保存在旧实验根目录。

- deepseek-budget-5cny.json，累计费用和每次调用记录，跨任务继续复用。
- api_budget.py，在每次请求前按高峰未缓存输入及 24,000 输出 tokens 预留费用，
  成功后按调用时段和实际 usage 更新，累计上限 0.60 美元，给 5 元预算保留余量。
- run_budgeted_release.py，固定绝对路径账本的模型运行辅助脚本。
- test_api_budget.py，预算预留、记账和超预算阻断的离线检查。

辅助脚本通过 PYTHONPATH 使用指定 worktree 的框架。切换工作目录时要检查 import 的来源，
并始终保持账本的绝对路径。正式请求前也要核对可用费率及账本，避免重置累计费用。
官方端点为 https://api.deepseek.com，模型为 deepseek-flash。
本地子进程已清空 OPENAI_API_KEY、VISUAL_API_KEY、DEEPSEEK_API_KEY。
平台运行使用平台注入的模型配置。

费用依据 https://api-docs.deepseek.com/quick_start/pricing/ 。

## 测试和送测包

1985aac 的框架与入口单测 48 项通过，日志在新 worktree 的
output/react-checkpoint-tests.log。此前固定浏览器后端的 13 项真实浏览器测试通过，
模型兼容 15 项、输入鲁棒 14 项、旧编译器 15 项、打包清单 1 项也通过。

旧目录 output/releases/compiler-react-671be45-20261115.zip 为候选包，463,589 字节。
SHA256 为 e9ca28edcff0a57c56dca4e6e70f5ad392809394906f31898c29949d1f85e9b2。
包内 agent-release.json 指定 react 引擎，并记录源码提交和全部文件指纹。
已检查根目录入口、依赖和运行时、文件指纹，以及本地凭据和输出目录的排除。
BookStack 首轮从这个包解压的固定入口运行，自动准备 Playwright，自动验收 12/12，
外部验收 10/12。

源码 checkout 的默认引擎为 staged，实验运行需加 --engine react。
打包使用 python scripts/package.py --engine react --output RELEASE.zip。
上传包通过 agent-release.json 默认选择 react，平台固定启动命令无需额外引擎参数。
自动浏览器工具固定为 @playwright/test 1.55.0，准备在生成应用外部。

本轮真实运行环境为 Windows + 已安装 Chrome。
Docker Linux daemon 未运行；WSL Ubuntu 因挂载 D:/WSL_Storage/ext4.vhdx 被拒绝而未能启动。
Linux Chromium 准备路径和云端送测仍待验证。

## 图与研究资料

框架图保存在旧实验目录 architecture/react-architecture.png 和 .svg。
采用双栏旧框架/Hybrid 结构，底部标明待验证项目，SVG 可以继续编辑。

研究及差异分析见 REACT_EXPERIMENT.md。已参考 mini-swe-agent 的线性对话与限额控制、
Deep Agents 的简化提示和工具设计、harness tracing 与验证循环、Playwright 官方定位文档。
早期平台日志和本地实验的环境、端点及缓存不同，时间比值仍需受控实验核验。
