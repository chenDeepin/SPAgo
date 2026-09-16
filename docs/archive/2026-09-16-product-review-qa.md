# 产品进度与 backlog 复核 Q&A — 2026-09-16

> 已归档 2026-09-17 — 本轮复核已完成，所有发现已在 register（`docs/plans/backlog.md` §1–§2）中分派；B-31/B-32 仍由 operator 把关。Q1–Q3 是实施第 1 轮之前的日期快照，不是当前状态；当前状态以 capability 文档和 register 为准。原文中的链接已按归档位置更新。

状态：**计划与文档阶段已整理；没有进入实施。** 核查基线：`efb1357`
（`main`，开始时工作区干净）。用户本轮明确要求不执行，只检查、规划、更新文档。
当前排序以 [backlog §1](../plans/backlog.md#1-priority-order) 为准；这里记录判断依据、边界和开放问题。

## Q1. 产品现在到底处于什么阶段？

**已有可运行的本地产品主干和部分真实来源记录，尚未完成真实托管试用验收，也未证明科学内容整体正确。**
不能把 M0–M5 的实现标签理解为产品愿景全部完成；尤其 claims、跨家族 SAR 和科学复核仍有明显边界。
本轮没有重新运行应用，以下历史验证均指仓库中已有的记录。

| 产品环节 | 当前实现 / 历史证据 | 仍不能据此声称什么 |
| --- | --- | --- |
| 专利 → 家族 → 化合物 → 结构过滤 | 当前路由、前端表格、RDKit 查询实现；B-03 容错专利号；B-17 的本地 synthetic 浏览器 smoke | 任意专利均已覆盖；全库或跨家族结构检索；本轮浏览器通过 |
| 靶点 → 来源 → 活性 / 证据 | UniProt、ChEMBL、BindingDB、PubChem 路径，确定性模态/效力政策；B-02/B-06 的历史 live 记录 | 薄覆盖代表不存在活性；跨 assay 数值可直接排名；当前所有来源仍可用 |
| 语料与来源覆盖 | B-01 批处理/库存；B-24 专利声明集合；B-26 三类覆盖；B-23 本地快照工具 | 声明等于专利出现；本地快照等于托管能力；覆盖报告含完整独立 snapshot leg |
| 人工与 agent 补充 | B-25 bundle、逐行拒绝、人工确认和撤回已实现，有本地交互记录 | agent 未确认结果等于人工事实；补充后的工作区统计等于纯公开数据库覆盖 |
| LLM 解释与历史 | family/document/target scoped summary；B-10 读取、陈旧提示、Markdown 导出；一个真实 provider 的历史测量 | 有效 citation 等于内容正确；多 provider 兼容；所有引用能定位确切记录 |
| 保存工作与导出 | 项目和身份/来源快照、家族及单靶点重开、CSV/SDF 已实现 | 混合项目可完整导航；靶点导出一定继承当前阈值与证据筛选 |
| 数据维护与部署 | B-04 限定范围的撤回与重跑恢复；邀请/owner/配额；本地 hosted-shape 演练 | 在线调查刷新已撤回遗漏行；真实域名/TLS/外部用户已验收 |
| 回归保障 | B-14 精选非数据库测试 + 前端构建 CI；B-17 一条本地成功路径 | 完整 PostgreSQL/RDKit 测试和浏览器 smoke 已进 CI；全部错误/过期状态已覆盖 |
| 明确未交付 | claim text、完整跨家族 SAR 工作区、PDF/OCSR、完整 Markush | 不能因产品愿景提到它们就标为已支持 |

主要记录：[托管形态演练](2026-09-16-hosted-acceptance-rehearsal.md)、
[B-17 smoke](2026-09-16-e2e-smoke.md)、[摘要历史](2026-09-16-analysis-history.md)、
[快照测量](../../benchmarks/bindingdb-snapshot-2026-09-16.md)、
[能力与验收门槛](../online-capability.md)。历史通过没有在本轮复跑。

## Q2. 本轮发现了哪些值得先处理的实际缺口？

以下为**静态调用链或文件内容已核对，运行时尚未复现**的发现。

| 发现 | 当前文件依据 | 对用户的影响 / 去向 |
| --- | --- | --- |
| 靶点显示阈值和 evidence filter 未完整传入导出 | `apps/web/src/App.tsx` 候选/测量查询与 ExportMenu 参数；`components/ExportMenu.tsx` 请求；`api/client.ts` 类型；后端 `api/routes.py::ExportRequest` 和 `services/export.py` | 下载成功但集合/分类政策可能与屏幕不同；**B-33，首个工程候选** |
| `/healthz` 的身份只有固定 API 版本 | `main.py` 使用 `__version__`；`spago_core/__init__.py` 为 `0.1.0`；`api/routes.py::HealthResponse` | 无法凭 API 版本区分多轮构建与旧服务；**B-34** |
| 完整测试未进 CI，已有 DB 镜像可复用 | `.github/workflows/checks.yml`、`scripts/run_checks.sh`、`docker/db/Dockerfile`、`apps/web/playwright.config.ts` | “等待有人提供镜像”不应成为永久 operator blocker；**B-35** |
| 混合项目能保存，重开导航不完整 | `SaveCandidatesDialog.tsx` 可追加任意项目；`App.tsx::openProject` 取首个可用项；switcher 只列 family | 同一项目里其他靶点/家族难以找回；**B-36** |
| 摘要引用多处只切标签页或显示文字 | `EvidencePanel.tsx`、`TargetEvidencePanel.tsx`、`AnalysesDialog.tsx` | 无法保证所见证据就是摘要所引记录；**B-37** |
| 来源刷新缺少明确的缺失撤回规则 | `services/discovery.py` 更新/恢复已有行，没有与完整覆盖范围对应的 absence 操作 | 当前记录与曾检索到的历史记录混在一起；**B-30 上调** |
| checkbox 键盘事件和虚拟表语义需检查 | `CandidateTable.tsx` / `CompoundTable.tsx` 的 row key handler、checkbox 和表头位置 | 键盘选中可能触发行检查；**B-19 上调**。`Modal.tsx` 已有焦点管理，不重复建设 |
| 小型筛选状态刷新后丢失 | `state/url.ts` 只有 q/doc/c/t；阈值、证据类别、模态是 React state | 重开同一问题可能换回默认政策；**B-39** |

B-30 必须先定义 target/source/access-path/query/release 范围。BindingDB REST 与
snapshot 共享 `source_name=bindingdb`，却有不同记录键；不能用一次 complete
REST 回答撤回 snapshot 的行。失败、partial 和未询问范围不能证明缺失。
普通 subset package 也不能证明整篇文档已从完整 release 消失。

## Q3. 哪些“已验证”的数字需要重新理解？

- [本地 cohort](../../benchmarks/cohort-coverage-2026-09-16.md) 的 TSLP verdict
  为 1/2 qualifies，包含该工作区补充数据的影响；
  [隔离演练 cohort](../../benchmarks/cohort-coverage-2026-09-16-accept.md) 为 0/1。
  `scripts/cohort_coverage.py` 把来源结果与整个工作区 verdict 放在一起，尚未单算
  source-only verdict。这是两套状态，不能合并成一个“公开数据库覆盖率”。
- 隔离演练中 IL-6 / IL-6R 未存入；另一轮使用 accession 的本地记录包含它们。
  一个环境的记录不能补齐另一个环境的验收。
- 模型测量含 synthetic family/document 输入；schema 与 citation 验证只说明
  输出符合合同。原始结构、立体化学、assay、出现位置、摘要主张的支持程度仍需独立交叉阅读。
- API `0.1.0` 不是唯一构建身份。保留原记录，不给历史 artifact 补写猜测的 commit。
- `services/coverage.py` 仍有“本 build 未配置 snapshot”的固定说明。工具已存在，
  但无独立 snapshot coverage leg；文档先纠正，运行时说明的修复进入 B-32，不在本轮改代码。

对应 **B-32**：分开 source-only 与 supplemented cohort，记录分母、来源路径、
resolved accession、阈值/模态、数据版本和构建身份，准备可复核样本；独立 reviewer 的
签读是 gate，agent 准备材料不等于完成独立验收。

## Q4. 为什么这样排序？

| 层级 | 当前建议顺序 | 理由 |
| --- | --- | --- |
| P0 | B-31 真实托管试用验收 | 产品能否交给受邀用户的实际门槛；operator、真实用户和独立读者参与不可省略 |
| P1 | B-33 导出一致性 → B-34 构建身份 → B-32 科学证据包 → B-35 全量 CI → B-36 混合项目 → B-37 引用定位 → B-30 刷新语义 | 先守住可带走的科学结果，再让验证可追溯、工作可找回、解释可核对；有 gate 的项不阻塞独立准备 |
| P2 | B-38 失败回归 → B-19 键盘可用性 → B-29 分析入项目 → B-39 重现状态 → B-21 claims 来源决策 → B-09 扩 catalog → B-11 拒绝说明/第二 provider | 加强已有用户闭环，再按实际问题增加覆盖；数据源与 provider 选择保持显式 gate |
| P3 | 有顺序的后续探索，见 backlog | 需要真实使用需求或测量后再提升，不因上层做完就自动开工 |

B-09 不再排第一：先复核已有 cohort，再扩展系统映射。B-21 值得提前做**来源可行性
决策**，因为 claims 是愿景缺口；这不等于批准新 ingestion。B-22 下移，OPS 是可能
方案之一。B-11 的拒绝解释可与第二 provider 采购分开。B-19/B-29 上调来自现有操作与
“解释 → 保存决策”需求，不要求增加常驻面板。

本轮按用户要求只形成排序；后续实施仍需选定小范围计划并重新核对当前代码。

## Q5. 有哪些值得保留的发散方向？

- **B-29：把已存分析附在项目选择上。** 保存选择的理由，保留原 citation、policy、
  版本和陈旧状态，不做通用报告平台。
- **B-39：恢复同一调查问题。** 首步仅保存小型靶点筛选参数；避免敏感内容进 URL，
  不把整个查询结果复制为第二套数据库。
- **B-40：小规模跨家族 SAR 对照。** 对已选少量结构做确定性 scaffold/测量并排比较，
  明示 assay 不可比；用户提出真实问题前仍是 LATER。
- **B-28：批量靶点与变更报告。** 先有可靠刷新语义，再谈 added/changed/withdrawn；
  不引入新服务或自动调度。
- **B-41：歧义专利号的候选选择。** 已有 exact-number workaround，等试用证明摩擦
  再实现。B-27 打印审阅单、B-20 中文界面同样由受邀用户的实际需要决定。

OCSR/Markush、通用聊天、额外基础设施和团队平台仍不进入当前实施范围。

## Q6. 哪些问题保留给下一轮，而不阻塞这次文档交付？

1. 谁是受邀科学家、独立科学读者，实际试用哪个目标/家族？决定 B-31/B-32/B-09 的样本。
2. 哪个 host/provider/budget，接受什么延迟/成本？本轮未选择、未采购、未调用。
3. complete / complete-empty 如何声明足够的 query/release coverage？B-30 的设计门槛。
4. 导出“选中项”遇到筛选改变时如何处理？在 B-33 中明确拒绝/保留规则，不能静默扩集。
5. 下一阶段 claims 来源和可复核样本从哪里取得？B-21 先做决策，不能默认 OPS 提供全部内容。

## 本轮交付与核查范围

- 更新 backlog 的开放项排序、分类、收益、依赖、验收草案和变动理由；保留已交付记录。
- 同步 `PROMPT.md`、能力说明、架构现状、README 的当前边界；演练计划增加历史记录标识。
- 已核对：Git 基线、当前源文件/配置、迁移文件、历史计划与 benchmark 的存在及内容。
- 文档检查通过：7 个 Markdown 文件的 53 个本地链接/锚点；26 个开放事项的唯一性与
  优先级/分类一致性；B-31…B-41 均有条目和排序；`rtk git diff --check` 无错误。
  两份独立只读复核提出的措辞冲突已修正；这些是文档检查，不是运行验收。
- 未执行：产品代码修改、测试、构建、服务/数据库操作、浏览器验收、外部 API/model、
  部署、commit、push。本轮没有新增 dependency，也没有关闭托管 gate。
