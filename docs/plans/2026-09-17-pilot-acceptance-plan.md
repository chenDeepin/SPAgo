# 下一阶段：真实试用与科学复核 — Q&A / 计划

状态：**规划完成，未执行验收或工程实施。** 核查基线 `c0d2cdc`，2026-09-17；
开始时 `main` 工作区干净。本文件服务仍开放的 **B-31 / B-32 / B-45**，不是新功能授权。
优先级以 [backlog §1](backlog.md#1-priority-order) 为准，正式验收以
[能力说明 §6](../online-capability.md#6-required-before-admitting-users) 为准。

## 1. Q&A：这次更新之后，判断发生了什么变化？

**上一轮的主要工程断点已经有实现与交付证据，下一步重点应转向真实用户和真实来源内容的验收。**
本轮核对当前源文件与历史记录，没有重跑测试、浏览器、CI 或外部来源，因此以下通过数字都是历史结果。

| 上轮关注点 | 当前核对依据 | 本轮结论 |
| --- | --- | --- |
| 靶点导出政策与筛选 | `ExportMenu.tsx` 已发送 threshold/evidence class；`App.tsx` 已传入；B-33 archived plan 有浏览器记录 | 不再作为待修产品缺陷；CI 中对应导出测试仍有 fixture 缺口 |
| 构建身份与 CI | `HealthResponse` 已含 build_id/build_source；workflow 有 full-stack job，构建实际 db/app 镜像并核对身份 | 工具已交付；当前服务是否匹配当前 checkout 本轮未检查 |
| 混合项目 / 引用 / 保存分析 / 状态恢复 | 当前代码有 saved scopes、typed citation navigation、project analyses、URL 筛选参数；B-36/B-37/B-29/B-39 有交付记录 | 不重开已完成工程条目 |
| 来源刷新 | `discovery.py::_retract_dropped_candidates` 按 target/source/access path 撤回 complete/empty 的缺失候选行；迁移 0021 | B-30 已交付；未记录路径的旧行、跨文档完整 release 缺失仍有明确边界 |
| 键盘、读屏与 Back | B-44/B-46 的 transcript/benchmark；B-43 当前代码与 history-step 记录 | 最新记录为本地浏览器 8 passed；不代表本轮通过或跨平台普遍验收 |
| 科学复核 | B-32 generator 与 source-only/combined 计算已实现；现有 pack 为 compact 历史汇总 | 机器半程完成，独立读者尚未签读；应在优先级表中显式保留 |
| 浏览器 CI 的实际范围 | 两个 spec 有无存量数据则 skip 的分支；已记录 CI run 35126623060：6 passed + 2 skips | “完整后端 CI”成立；“所有浏览器关键回归均在干净 CI 执行”不成立 |

最新本地记录：[B-43](../archive/2026-09-17-history-step.md)；
CI 范围记录：[B-38](../archive/2026-09-16-browser-regression.md)。
本轮未查询远端 CI 状态，不能据这些记录声称 `c0d2cdc` 的远端检查刚刚通过。

## 2. Q&A：现在最应该做什么？

1. **产品主线：B-31，组织一次真实托管试用。** 明确主机、预算、数据范围与参与者，
   在选定构建上完成 §6 的部署、恢复、隔离、模型、覆盖和用户脚本。
2. **科学主线：B-32，重建完整材料并安排独立交叉阅读。** 已有脚本无需重写；
   需要补的是对应这次 build/data 的逐条材料和人的判断。
3. **可并行的小工程：B-45。** 把现有导出/重试用例从“工作站有数据才运行”改为
   “隔离合成调查 fixture 在干净 CI 中可重复运行”，同时消除 resolve 的在线依赖。
   这是等待 operator/reviewer 期间可推进的事项，不是替代真实试用，也不是新添 §6 门槛。
4. **试用后再选增量功能。** B-21 claims 来源决策、B-09 新靶点映射仍需实际需求与
   operator/reviewer 输入。B-40 SAR、B-47 assay 条件、B-28 批量报告等保持 LATER。

排序变化：B-32 恢复到 P1 开放表；B-45 从 P3/LATER 上调为 P2/NEXT 首个工程候选。
理由是已知 CI 跳过范围，不是为了在队列清空后继续制造任务。未新增编号。

## 3. 首先需要明确的输入

以下在仓库的当前验收记录中尚未完成；本轮不代填秘密、选择付费提供方或发出邀请。

| 输入 | 责任人 | 待记录内容 | 用途 |
| --- | --- | --- | --- |
| 试用目标与参与者 | 产品 owner | 1 位非实现者科学家、1 位独立科学读者；真实问题、目标/家族、预计会话量 | B-31 用户脚本；B-32 样本；B-09 是否需要扩展 |
| 主机与访问方式 | operator | host/domain、HTTPS、私有数据库、备份位置/周期、邀请方式 | §6 部署/隔离/恢复；参考 runbook H1–H7 |
| 模型与预算 | operator | 本轮采用的 endpoint/model、可发送数据范围、非零 token quota、月度支出和响应时间目标 | §6 模型/成本；填 runbook H9，历史测试过一个模型不等于本轮已选择 |
| 科学范围与政策 | owner + reviewer | resolved accession、物种、模态、阈值/minimum、来源/版本、是否允许用户补充 | coverage matrix、source-only/combined 的可比口径 |
| 候选版本 | 实施者 + operator | 精确 revision/image、served build_id、schema、数据清单、pack generator 身份 | 所有验收材料属于同一次候选状态 |

不必先扩 catalog 或接入第二 provider 才能试用现有范围。主机或参与者暂不可用时，
可准备材料或实施 B-45；本地演练仍必须标为 rehearsal。

## 4. 计划顺序与可审阅交付物

### A. 固定候选与数据范围

后续实施获授权后，选定候选 build，复核该版本相应检查。部署前记录 revision/image；
部署后比较 `scripts/build_identity.py` 的 expected/served 身份，并核对数据库迁移。
当前仓库到 0022，**不据此推断任何运行数据库也已到 0022**。同一个 `-dirty` 标签可能
对应不同工作树，正式候选应记录精确镜像/构建输入，不能只靠这个后缀区分前后两次构建。

真实试用使用已确认可用且允许处理的数据；synthetic demo 仅用于机制测试。
材料中分别记录来源数据、快照路径和手工补充，保持声明专利与语料 occurrence 的区别。

### B. 生成当前候选的科学复核材料（B-32）

- 现有 `benchmarks/cohort-pack-2026-09-16.*` 记录 generator `eb486d0-dirty`、
  served `d9f441a-dirty` 和 schema 0020，并经 `--compact` 省略逐条记录。
  它可说明历史统计，**不是当前 0022 候选的逐条复核材料**。
- 用已有 `scripts/cohort_pack.py` 为确定的数据库/构建生成不带 `--compact` 的完整包；
  指明 generator 身份、served 身份和连接的数据范围。`/healthz` 身份匹配不能单独证明
  脚本读取了正确数据库，operator 需要核对配置与数据清单。
- 全量逐条包放在仓库外的审阅目录；仓库最多保留小型公开/合成样本及允许提交的汇总。
  生成 pack 读取存量数据，不等于重新检索来源。是否刷新来源须在冻结样本前决定，不能
  在复核中途静默变更数据。
- 建议先挑 12–20 条公开来源记录作为有边界的初始样本，按实际可用层分布：结构/立体、
  直接结合/功能性证据、`<`/`>`、非 potency、薄覆盖/失败来源、声明专利/语料出现、
  人工补充与未确认 proposal。不是每层都有记录；缺层列为未覆盖，不伪造来源填满。
  样本数量是建议，不代替 §6 判定，也不支持总体准确率推断。
- 附上至少 family/document/target 各范围的可用摘要与其冻结输入/citations；
  记录缺少哪类真实输入。人工签读不能只查 citation id 存在，还需查主张是否由来源支持。

Reviewer 表至少含：record/citation id、原始 URL/DOI/专利定位、source/access-path/version、
要核对的事实、pass/discrepancy/unverifiable、理由、reviewer/date、处理结论。
无法取得原文的记录是 unverifiable；机器生成和签读结果分开存放。

### C. 补齐实际 CI 执行范围（B-45，可与 A/B 并行）

复用现有 runner、seed/import/service 合同，在可销毁的 CI 数据库准备少量合成
target/candidate/measurement/retrieval 行，并控制 resolve/upstream 响应。
不往用户数据库灌测试数据，不用真实来源“制造 fixture”，不增加生产测试 API。

导出测试必须读取真实本地 API/数据库生成的 CSV，不能 mock 正在验证的导出结果；
重试浏览器用例的 upstream fixture 仍只证明 UI/请求范围，持久化由后端测试承担。
CI fixture profile 缺数据或 API/授权错误应失败，不能自动 skip。
验收目标是干净 runner 实际运行两个用例、无来源网络依赖，并报告执行/跳过计数与构建身份。

### D. 真实部署与非实现者 walkthrough（B-31）

沿用 §6 和 runbook H1–H10，不另造一套宽松验收：检查 HTTPS/auth/readiness、
两个账号隔离、实际 host 的 dump/restore、来源 coverage matrix、一个本轮选定模型的
family/document/target smoke、quota/用量、H9 目标与测量。

由非实现者科学家完成现有八步脚本；在适用处观察近期修复的行为：阈值/筛选后导出、
引用定位、混合项目保存与重开、Back 恢复原范围。记录失败与困惑，不在后台替用户完成
后再声称用户独立通过。B-32 独立读者输出与同一候选材料绑定。

### E. 收口

输出一份按 §6 criterion 对照的 pass / failed / blocked / not checked 记录和 artifact 链接。
发现的缺陷先记回本计划与 backlog，按科学错误/数据隔离/主流程阻塞优先修复，复跑受影响
部分；本地替代或更改 checkbox 不能关闭失败。只有实际材料支持时才能决定是否开放给
受邀用户；剩余范围、负责人和决定保留。后续功能从试用证据选择。

## 5. B-21 的并行决策边界

[claims 来源 dossier](2026-09-16-claims-source-feasibility.md) 已准备，仍未选择来源。
先明确是否将 claims 纳入这次 pilot；不纳入则保留“claims 未评估”边界，无需让 OPS
阻塞现有产品试用。若选择探索，重新确认条款/credential 与小型真实 publication 样本。
`DEMO-*` 是 synthetic 标识，不能作为实际 claims endpoint 的覆盖率样本；取得 claim
文本也不能自动证明某个化合物落入权利要求范围。

## 6. 本轮检查记录

已检查：Git 状态与提交增量、当前关键调用链、CI workflow 和 skip 分支、迁移列表、
历史交付记录及 compact pack 的构建/schema/省略字段。本轮只做文档更新。

未检查：运行中服务及数据库状态、当前远端 CI 结果、浏览器/测试重跑、live 来源、
托管验收、独立科学签读。未执行部署、付费调用、发出邀请、commit 或 push。

文档检查通过：6 个 Markdown 文件、21 个本地链接/锚点；47 个 backlog 编号无重复，
17 个开放项的优先级/分类与正文一致（P0=1、P1=1、P2=3、P3=12）；
`rtk git diff --check` 无错误。新建本文件是为了保留上述开放 gate 的实际工作计划。
