# UI 与规则复查 / 当前修复计划

日期：2026-09-14。复查基线：`d0e2371`，开始时工作区干净。
更新：2026-09-15（第二轮），修复已实施并完成本轮验收，见「2026-09-15 修复实施与验收记录」。
第一次更新（2026-09-15 核对基线 `f3da90c`）保留为修复前的核对表；UI-07/08 与 LLM-05–07 现已关闭。
范围：复查此前 AGENTS.md 适配、UI 草稿与设计指引，并与当前实现定向对照。不是完整代码、安全或科学正确性审计。

**当前交接（产品可用性复查）**：后续执行转至 [产品可用性与首版计划](2026-09-15-product-readiness.md)。UI-07/08、LLM-05–07 的指定修复保持关闭；下文“全部执行”仅指该轮修复，不代表原验收矩阵或产品全部通过。本轮新核验发现结构过滤后 “Current results” 仍导出全同族（1 条筛选结果对应 10 条 CSV），项目重开入口也未接通，分别记为 PROD-02/03。真实来源、默认 DB 暴露和恢复/交付门槛一并在新计划中跟踪，避免仅安排 Ketcher/Chrome 而遗漏真实使用闭环。保留本文件及尚未提交的验证材料，后续归档时更新全部引用。

## 2026-09-15 修复实施与验收记录（第二轮，UI-07/08 + LLM-05–07 关闭）

### 环境与对应关系

| 项 | 值 |
| --- | --- |
| 代码 | `f3da90c` + 本轮工作区改动（后端 `services/core/spago_core/**`、测试、前端 `apps/web/src/**`、`scripts/mock_llm_endpoint.py`） |
| 镜像 | 由当前 checkout 构建的 `spago-app:m0`（`8b48aed6b8e8`，构建时间 2026-09-15 ~01:28 +08:00）与 `spago-db:pg15-rdkit` |
| 隔离服务 | `spago-verify-app`（127.0.0.1:8055）+ `spago-verify-db`，独立网络 `spago-verify-net`；不使用开发栈、用户数据库 |
| 数据集 | 合成为主：`demo-fixture-v1`（10 化合物）+ `paging-501-fixture-v1`（601 个唯一化合物、1 文档、601 条证据、0 测量）。两个 manifest 均标 `synthetic: true`，界面顶部同时显示 Demo dataset 标记 |
| 浏览器 | in-app browser；1440×900、1024×800、760×800 |
| 后端测试 | `rtk proxy .venv/bin/python -m pytest`（services/core）：**157 passed**（历史 125 + 本轮 32） |
| 前端 | `npm run build`（Node 22）：passed；主包 254.99 kB / 78.81 kB gzip（本轮前 ≈249 kB / 77 kB） |

图片证据：`docs/plans/ui-round-verification/paging-601-lastpage-1440.png`、`paging-error-retry-1440.png`、
`paging-error-760.png`、`paging-1024.png`、`paging-760.png`、`llm-760-success.png`、`llm-waiting-760.png`。

### UI-07 普通结果真正分页（关闭）

实现：`api/client.ts::compounds` 增加 `offset`；`App.tsx` 普通列表改为 `useInfiniteQuery`
（`initialPageParam=0`，`getNextPageParam` 用服务端 `offset+items.length < total` 推进），页面按 offset 追加，
表格仍只渲染可见行；`compoundsLimit` 状态删除。结构分支与普通分支都显示分页错误。

验收（1440×900，601 化合物家族）：

- 首次只有 1 次 `?limit=100&offset=0` 请求；连续 Load more 依次产生 `offset=100,200,300,400,500,600`，
  每次 `limit=100`，无重复下载不断增长的第一页（浏览器 `performance` 资源条目为证）。
- 页脚依次 `1–200 → … → 1–600 → 1–601 of 601`，末页后 Load more 消失（第 7 次点击无按钮可点）。
- 601 行全部加载后 DOM 仍只有 13 行（虚拟化成立）；滚到 `data-index=600`（第 601 行）可打开证据面板
  （Example 0580、page 581、provenance `machine_extracted`、dataset `paging-501-fixture-v1`）与结构抽屉
  （canonical SMILES/InChIKey/InChI 齐备）。
- 表头全选只选中已加载行：页脚显示 `601 selected for save/export`。
- 换家族（DEMO-PATENT-A）后再切回：新家族页脚 `1–10 of 10`，回切显示 `1–601 of 601` 且未产生重复请求
  （同一 family+document 键的缓存内页面被复用，没有串族或重复追加）。
- 1024×800 / 760×800：无横向溢出（`documentElement.scrollWidth` == 视口宽），Load more 可用并推进到
  `1–200 of 601`。
- 服务端分页契约（601 夹具、真实 PostgreSQL）：`tests/test_paging_beyond_cap.py` 5 项通过——顺序稳定、
  分页不重不漏、`offset=500` 返回 100 行、`offset=600` 返回 1 行、越界返回空且 total 不变、
  `limit=99999` 被钳到 500、结构检索同样可到第 501 行之后。

### UI-08 结构分页错误/重试、作废与作用域（关闭）

实现：结构 Load more 绑定 `AbortController`，错误连同 `requestKey` 一起保存，只有当前 requestKey 的错误
才显示；关闭对话框、移除过滤、换家族/文档/查询时中止在途请求并清空错误；普通分支用
`isFetchNextPageError` + `fetchNextPage` 重试。行解析改为「当前展示范围优先」：结构检索激活时从结构结果
解析查看行/结构抽屉，普通页作为后备；全选使用当前展示范围。

验收：

- 分页失败（停止 app 容器模拟来源不可用）：已加载行保留（`1–100 of 601`、DOM 仍渲染行），
  `role=alert` 显示 `Source unavailable: the SPAgo service could not be reached.`，
  操作变为 `Retry load more (501 remaining)`；恢复服务后点击重试追加成功 → `1–200 of 601`，错误消失。
  同一失败路径在 760×800 复现并截图。
- 结构独有结果作用域：仅加载普通首屏 100 行时运行亚结构检索（`C(=O)O`，601 命中），
  在第 146 行（结构序 index 145，API 核对确认其 InChIKey 不在普通首屏 100 行内）点击即可打开证据面板与
  结构抽屉——这是修复前 `selectedRow`/`structureRow` 只查普通 `compoundsQuery` 会静默失败的场景。
- 迟到响应作废：同一次页面任务内点击 Load more 后立即 Remove ×，结果显示过滤条消失、页脚回到普通
  `1–100 of 601`、无错误条、无多余请求条目——迟到结果没有追加到已切换的视图。

### LLM-05–07（关闭）

实现位置：`services/core/spago_core/services/ai.py`（预算与错误类型）、`adapters/llm.py`（超时与 429）、
`api/routes.py`（状态码/头映射）。

- **LLM-05 输入预算**：`_collect_family_facts` 的 scaffold 聚合加 `LIMIT`（保留 `scaffold_total`），
  摘录按 UTF-8 字节（≤1 KiB）裁剪并标记 `excerpt_truncated`；新增 `finalize_snapshot()`：先裁剪摘录，
  再写入 `input_note` 与各类 omitted 计数，然后对**最终 body**复核 32 KiB 预算，按「当前最大可选列表」
  逐个移除整条事实；若必需元数据本身超限则抛 `SnapshotBudgetError`（500），不调用 provider、不写成功缓存。
  离线文本改为按 `measurement_total` 描述，不再把「被裁剪」说成「不存在」。
- **LLM-06 超时**：`timeout=self.request_timeout` 现在真正附到 `build_request`（此前请求用 httpx 默认
  5 秒，声明的 60 秒预算未生效）；deadline 在调用前与每个 chunk 之间检查。
- **LLM-07 上游 429**：新增 `LLMUpstreamRateLimitError`（429）与 `parse_retry_after()`（接受 delta-seconds
  或 HTTP-date，无效值不猜测）；路由在有效值时回传 `Retry-After` 头。

验收（`tests/test_llm_contract.py` 24 项 + `test_llm_adapter.py` 更新 + `test_m5_ai.py::TestSnapshotBudgetBoundary`）：

- 预算：超限快照被裁到 ≤32 KiB（含说明与计数），中文摘录按字节裁剪且不切开字符，无可删条目时明确失败；
  孤立核验（数据库级）证明失败前 provider 调用数=0 且 `ai_analyses` 无新行。
- 慢端点：使用 127.0.0.1 本地可控慢端点（首次字节延迟、持续慢流）验证 deadline 生效、返回 504、
  失败后客户端仍可用；另有请求断言证明 `read` 超时等于声明预算而非 5 秒默认。
- 429：adapter 与 API 双层断言；并用改造后的 `scripts/mock_llm_endpoint.py` 在隔离栈上端到端复现：
  上游 429 + `Retry-After: 7` → SPAgo 返回 **HTTP 429 且响应头 `retry-after: 7`**；
  上游 429 + 无效头 → 仍 429、无 `Retry-After`；上游 500 → 仍 502（未被误映射）。
- 浏览器（隔离栈 + mock 端点，1440×900 与 760×800）：configured 状态显示模型名；LLM 生成成功
  （chip `LLM inferred · llm-openai-compatible · mock-model`、3 条 measurement 引用）；换化合物重复生成
  命中缓存（chip 追加 `cached`，mock 端点 POST 计数不增加）；上游 500 显示错误条且不落结果；
  `mock-timeout` 下 Stop waiting 回到空闲且文案说明不表示供应商已停止计费；切换家族后摘要不残留。
- 迁移：`tests/test_migration_0006_upgrade.py` 在独立 scratch 数据库上完成 0005→0006 前向升级：
  0005 形状的旧分析行文本/引用不变、新列为 NULL、不被当作缓存命中，升级后新写入使用内容键且重复调用命中缓存。

### 未检查 / 缺口（诚实记录）

- **真实模型 smoke：not checked**（本环境无供应商凭据）。mock 与本地慢端点只证明协议子集、超时与 429
  契约；不证明任何真实供应商兼容性。真实端点首次生成仍需部署者执行并记录目标、usage、耗时。
- **真实专利/活性来源：not checked**。本轮所有数据均为 fixture（`synthetic: true`）；专利解析、族信息与
  化合物仍来自 `surechembl_simplified_fixture` 适配器，不是 SureChEMBL/OPS 在线数据。
- **Ketcher 嵌入、Chrome 扩展实际加载**：仍未验收（与本轮范围无关）。
- **性能口径**：`benchmarks/paging-beyond-cap-2026-09-15.md` 记录本轮测量（100 行页 67.7 KiB/13–19 ms、
  500 行页 341 KiB/41–45 ms、601 行滚动 ≈1.25 s、视口内 13 行、238 次描图请求）。该夹具无活性数据，
  与历史 150 条基线不可直接比较；未测并发、多 worker、冷描图生成与缓存淘汰。
- **未覆盖的交互**：键盘 Tab 循环、URL popstate 恢复、导出/保存的写入核对沿用 2026-09-14 记录，
  本轮未逐项重跑；结构分页错误未在家族切换中途（非同步 abort 路径）用真实慢响应复现，
  仅以同步 Remove 路径 + requestKey 归属断言覆盖。
- 开发栈（`spago-app-1` / `spago-db-1`）已在验收后按当前镜像重建（`docker compose up -d`）：healthz ok、
  `ai/status` = offline（未配置模型）、服务的前端包为 `index-DxHPx9Jh.js`（本轮构建产物）、
  demo 家族 offset 分页可用。重建不会修改数据库卷；验证用隔离栈与临时夹具已删除。



## 2026-09-15 更新核对（第一轮，修复前状态；保留作对照）

### Q&A：修复前的事实、缺口与顺序

| 问题 / ID | 已核对事实 | 处理 |
| --- | --- | --- |
| 是否有未同步提交？ | `git ls-remote origin refs/heads/main` 返回 `f3da90c5ca8b57fac38a3bb2b31da031d42ac8c3`，与本地 HEAD 一致；开始时 Git 工作区干净。沙箱内首次 DNS 解析失败，获准的只读远端检查成功。 | 无需拉取/合并；本轮不提交、不推送。 |
| 最新功能是什么？ | `f3da90c` 在 `6c33eea` 的 UI 修复后增加可选 LLM 摘要、迁移 0006、状态接口、typed citations、缓存及 mock 检查。 | 将 PROMPT/计划/设计指引中“LLM 尚未实施”改为“已实现，验收未完成”。 |
| UI-07 / P1 | `App.tsx` 普通列表只将 `compoundsLimit` 从 100 增至 500；`api/client.ts::compounds` 没有 offset 参数；服务端 `list_family_compounds` 已有稳定排序、OFFSET/LIMIT。 | CORE：复用已有后端分页，客户端按页追加；用至少 601 个唯一合成化合物覆盖第 501 条及末页。**已实施并完成浏览器+服务端验收（见上文第二轮记录）。** |
| UI-08 / P2 | `App.tsx::loadMoreResults` catch 无错误状态；请求也没有 AbortSignal。 | CORE：保留已加载行，显示可重试分页错误；关闭/移除结构查询、换同族/文档/查询时作废旧请求和错误。**已实施并完成浏览器验收。** |
| LLM-05–07 | 本地检查证明 snapshot 可超限、声明超时未附到请求、上游 429 映射 502。 | CORE：先完成 [LLM 纠偏及验收](2026-09-14-llm-interface.md#2026-09-15-纠偏-qa-与验收)，再做真实模型 smoke。**三项均已修复；真实模型 smoke 仍 not checked。** |
| 150 条 fixture / 125 项历史测试能否关闭所有缺口？ | 历史分页 fixture 只有 150 条；LLM 浏览器记录为 1440×900 和本地 mock；迁移只记录从零应用。 | 保留历史通过，不宣称 >500、760px LLM、已有 0005 数据升级或真实来源通过。**本轮以 601 夹具、760px LLM 场景与独立 0005→0006 升级测试补齐。** |
| 下一步是否进入 M6？ | 尚无真实专利来源端到端验收，Ketcher/Chrome 加载仍缺口；没有缺失覆盖测量支撑 OCSR。 | 不进入 M6；先修当前闭环，随后补真实来源与输入/扩展验收。 |

### 执行计划：CORE 修复与验收（已全部执行，结果见上文第二轮记录）

1. **LLM 契约纠偏**：在现有 `ai.py`、`adapters/llm.py`、`api/routes.py` 及相关测试内修 LLM-05–07，按 LLM 计划逐项留存失败复现与修复后证据。保持缺省离线、typed citation、内容缓存、单 worker 部署与「超时/限流/鉴权/传输故障不重试」；不扩展聊天/模型管理。（2026-09-15 更新：内容被拒时有界重采样一次，见 [live smoke 记录 §9](2026-09-15-llm-live-smoke.md)。）
2. **普通结果真正分页**：修改 `App.tsx` 与 `api/client.ts`，优先复用已安装的 TanStack Query 分页能力和现有表格，不新增请求框架。每页默认 100、单响应最多 500，下一页用服务端 offset/limit/total，不重复下载不断扩大的第一页；末页停用 Load more。将 family/document/query 纳入当前作用域；切换后作废旧页，避免重复追加或串族。
3. **结构分页错误及选择回归**：给现有 Load more 提供错误/重试和 AbortSignal，错误归属当前 requestKey，旧请求的 catch/finally 不得改写新请求状态。检查查看行、结构抽屉、全选已加载、证据、保存和导出取自当前展示范围。现有 `selectedRow`、`structureRow`、`toggleSelectAllLoaded` 读取普通 `compoundsQuery`；需以“结构结果含普通首屏未加载化合物”场景验证，不能仅在普通首屏内点击后宣称整个结构结果闭环可用。只修复复现出的作用域问题，不扩展导出能力。
4. **验收与记录**：先运行受影响测试与现有 frontend build，再启动当前 checkout 的隔离测试服务进行浏览器验收。明确进程/镜像对应代码、时间、来源模式、viewport；不使用用户数据库做造数或清空。LLM 的真实 smoke 在目标已明确配置且授权后执行，否则保持 not checked，不阻塞本地修复记录。

验收矩阵：

| 场景 | 通过标准 |
| --- | --- |
| 普通/结构分页 | ≥601 个唯一、明确标注 synthetic 的化合物；服务端与浏览器均能到达第 501 条和末页，顺序稳定、不重不漏、每次响应 ≤500；旧 150 条测试和基线保留。避免仅复制同一结构造数被归一化去重，也避免无限增长烷烃链冒充分页性能夹具。 |
| 状态与过期响应 | 首次 loading/empty/error、后续分页 source unavailable/错误/重试；失败保留已加载行与当前选择；重复点击不重复请求；加载中切族、换文档、换结构、移除过滤后迟到成功/失败不污染当前视图。 |
| 选择→证据→保存/导出 | 普通后续页及结构独有结果可检查证据/大图、全选当前已加载行、保存后重载；明确所选/同族/文档/结构查询的支持范围，无法表达的导出范围不能静默扩为整个同族。用 API 请求对象与输出记录核对范围，不仅检查 toast。 |
| LLM | LLM-05–07 单元/adapter/API 和本地慢端点检查；旧离线/缓存/引用回跳回归；隔离 0005→0006 升级保留旧分析；1440×900、760×800 覆盖成功/错误/停止等待/换同族。真实模型单独记录目标、usage、耗时及缓存外部调用数。 |
| 浏览器与性能 | 1440×900、1024×800、760×800；settled 截图及请求证据；测量分页响应耗时/字节、描图请求/可见行、滚动与内存，和既有 benchmark 并列保留。未测指标不得宣称无回归。 |

### 本轮后的顺序（2026-09-15 第二轮后更新）

- **NEXT：真实来源最小闭环**。先核对当前 patent source 仍为 fixture 的限制，选择一个有明确来源/版本的最小真实专利案例，按官方 API、批量数据或用户提供数据规划接入；ChEMBL 在线、BindingDB 文件验证分开记录。不要把活性 adapter 测试当成真实专利发现已实现。
- **NEXT：真实模型 smoke**。由部署者配置一个已授权端点后执行一次最小生成，记录目标、model、usage、耗时与缓存命中时的外部调用数；不得用 mock 结果代替。
- **NEXT：Ketcher 与 Chrome**。分别核实构建阻碍/最小嵌入路径、实际加载 MV3 的用户主动跳转；只在前一修复轮关闭后独立定范围。Ketcher 绘制仍复用现有结构查询对话框，Chrome 仍为可选入口。
- **LATER**：自由聊天、自然语言 planner、跨同族推断、大规模导出任务、经覆盖评估才可能需要的 M6。**REJECT**：Espacenet 自动化、新网关/并行运行时、无证据法律或科学结论。

### 第一轮文档更新验证（2026-09-15，修复前）

- 已检查：本地/远端提交、当前规则、交接/计划/设计/架构和定向源码；未修改产品代码、迁移、夹具、配置或截图。
- 36 项 adapter/chemistry/planner 测试、前端 TypeScript noEmit：passed；准确命令和 LLM 边界观察值见 LLM 计划末节。历史全套 125 项未重跑。
- `rtk git diff --check` 与 7 份变更文档的代码围栏、行尾空白、11 个本地链接/锚点检查：passed。
- 未检查：当前浏览器、生产 build、数据库集成/升级、真实模型/来源、性能；本轮不把源码检查写成浏览器通过。
- 变更范围：`PROMPT.md`、`README.md`、本计划、LLM 计划、架构 overview、UI 设计指引及 M1–M5 归档记录的后续链接。两份当前计划因纠偏/验收仍开放而保留；关闭时再归档并更新链接，不移动无关历史。

## Q&A：本轮发现与处理

| ID | 已核实发现 | 本轮处理 |
| --- | --- | --- |
| DOC-01 | 设计指引仍称仓库只有文档，但已有 apps/web、services/core 和迁移。 | 修正时间语境，标注源码核对与运行验证的区别。 |
| DOC-02 | README/PROMPT 和 M1–M5 记录笼统宣称完成，记录本身又说明 Ketcher 延期、Chrome 未加载及无真实 LLM。 | 限定为本地演示实现，保留历史测试记录，明确验收缺口；不宣称历史测试失败。 |
| DOC-03 | AGENTS 的浏览器验收规则未区分纯设计交付，可能被误读成草稿也需要应用运行证明。 | 补充纯文档/设计检查边界，保留实际 UI 变更的浏览器验收要求。 |
| DOC-04 | 草稿 Database curated 标签与当前 machine_extracted 夹具不对应。 | 要求来自 API 的状态映射；Demo、来源状态、置信度分别表达，不能照图硬编码。 |
| DOC-05 | 设计未区分模态焦点约束和桌面非模态证据区；取消文案未区分请求作废和服务取消。 | 修正交互契约，避免键盘锁死及虚假取消状态。 |
| DOC-06 | 架构 overview 仍以 M0 为“current”，将已实现能力描述成未来工作。 | 标为 M0 历史快照；下一轮对照代码整合当前契约。 |

草稿图仍为设计参考，不是可运行截图。结构检索图只采纳前景对话框；其背景多同族/HBA 内容不作为实现依据。此次不重新生成图片，避免用另一张示意图代替行为验证。完整生成提示词保留不改写。

## 原定向代码发现与修复结果

下表保留原发现及随后修复轮报告的验收结果；新的源码检查与未解决边界另外记录，不以历史通过替代当前全量验收。

| ID / 优先级 | 源码依据与风险 | 验收结果（2026-09-14） |
| --- | --- | --- |
| UI-01 / P1 | `StructureSearchDialog.tsx` 未传 AbortSignal，关闭后请求仍会调用 onResults；结果不携带同族/请求版本。 | **已修复并验证。** 每次请求绑定 AbortController；关闭/卸载即 abort（`closedRef` + 清理函数），abort 后不调用 onResults；结果携带 `familyId`/`requestKey`，`applySearchResults` 在同族不匹配时丢弃。浏览器验证：Run 与 Cancel 同步触发后对话框关闭，旧过滤条（[Na+] · 1 result）未被迟到的 150 条响应覆盖。 |
| UI-02 / P1 | `looksLikeSmiles` 强制含 C/N/O/c，拒绝 `[Na+]`、`S` 等合法结构。 | **已修复并验证。** 客户端仅检查"非空且无空白"的格式边界；化学有效性由 RDKit 服务端判定。浏览器验证：`[Na+]` 通过前端并命中钠盐记录（1 条结果）。 |
| UI-03 / P1 | 结构查询固定 limit=100 且未携带分页契约；前端以 rows.length 充当 total。 | **已修复并验证。** 结果携带服务端 total/offset/limit；表格显示真实总数并提供 Load more（追加下一服务页，普通表同样支持，上限 500 由服务端钳制）。以 150 条最小合成夹具验证：total=150、两页键集合不相交、`limit=99999` 被钳到 500（`tests/test_paging_contract.py`，3 项通过）。 |
| UI-04 / P2 | `Modal.tsx` 无 Tab 循环。 | **已修复并验证。** Tab/Shift+Tab 在面板内循环（首个⇄末个），Escape 关闭并归还焦点到触发控件。浏览器验证（1440×900 与 1024×800）：12 次 Tab 序列全部落在面板内；Shift+Tab 自首元素环绕到 Save；Escape 后焦点回到 "Save to project"。非模态证据区未改为模态。 |
| UI-05 / P2 | URL 只有 replaceState，无 popstate 恢复。 | **已修复并验证。** 粒度定义：新查询 pushState（Back 回到上一查询），文档范围/选中对象 replaceState；`subscribeUrlState` 在 popstate 时恢复 q/doc/c。浏览器验证：`history.back()` 恢复 `?q=DEMO-PATENT-A`（1–10 of 10），`forward()` 恢复分页夹具家族；大结构不入 URL（查询由 q 重放）。 |
| UI-06 / P2 | 所有模式显示 Preserve where specified；similarity 的 Morgan 指纹不区分立体异构体。 | **已修复并验证。** RDKit 实测：默认 Morgan 下外消旋/（S）布洛芬 Tanimoto=1.0（不区分）。文案按模式区分：exact/substructure 显示保留指定立体信息（亚结构含手性复核），similarity 显示"指纹法不区分立体异构体"。未改动指纹或化学预期。 |

## 修复轮新观察（未构成缺陷，记录在案）

| ID | 观察 | 处理 |
| --- | --- | --- |
| UI-OBS-1 | ≤1024px 时证据覆盖层展开会遮住表头 Save/Export 按钮，需先关闭抽屉。 | 与设计指引"小屏证据改为覆盖抽屉"一致；不做额外改动。若后续小屏保存成为常用路径，再评估抽屉高度/工具可达性。 |
| UI-OBS-2 | 该环境 IAB 中 Alt+方向键不触发历史导航；popstate 路径用 `history.back/forward` 验证通过。 | 真实浏览器返回按钮走同一 API，无需改动；记录环境差异。 |

## 下一轮计划：先修已有闭环（已执行完毕，留存作对照）

分类：CORE（修复已存在查询/证据/选择行为）。不新增架构服务、永久面板或科学推断能力。

### 1. 查询与结果范围

- 先为 UI-01/02/03 建立失败场景，再做最小修复；复用 API client 已支持的 AbortSignal。
- 结构结果关联 family、必要的文档范围和查询版本；切换上下文同步处理结果、查看对象和批量选择。
- 明确全同族检索与当前文档筛选的组合方式，并确保保存/导出复用同一作用域，不静默导出其他对象。
- 接通服务端分页，不增加客户端全量化学过滤。

### 2. 模态、导航与科学说明

- 修复 UI-04/05，覆盖鼠标及键盘；不要因统一焦点代码把非模态区域变成模态。
- 复核 UI-06 的 RDKit/cartridge 实际行为。涉及匹配算法或身份语义变化时，增加独立科学验证；文字修改不能作为正确性证明。
- 产品文案说明用户可用输入与限制，不暴露 bundler 崩溃等实现细节。

### 3. 验证与交接

- 读取实际 package.json、Python 测试配置和服务状态后选择命令；本轮已确认前端 build 脚本存在，但没有前端 test 脚本。新增测试工具前先检查可复用依赖并说明必要性。
- 执行受影响的 chemistry/API 集成测试、前端 build、查询取消/分页/模态/导航交互测试。数据库或外部服务不可用时说明 skipped/blocked，不能记通过。
- 使用当前 checkout 启动的浏览器页面在 1440×900、1024×800 和一个小屏尺寸验证；保存截图路径、来源模式、请求/结果证据和服务启动信息。图像生成草稿不计入验收。
- 用规模足够覆盖分页及虚拟化的合成夹具测量载荷、可见描图请求、滚动和内存；记录环境与原始结果。保留历史基线，不用新结果覆盖旧测量。
- 将 overview 更新为代码对应的当前契约，补齐可追溯验收记录；只有被验证的条目才关闭。将剩余问题写回本文件 Q&A，再决定下一个计划。完成后按 AGENTS 的归档规则处理本轮材料及引用。

## 后续升级提案

| 分类 | 升级 | 启动条件与完成依据 |
| --- | --- | --- |
| NEXT | Ketcher 嵌入 | 核实当前生产构建失败原因；最小集成复现通过后接入已有对话框，绘制→执行→证据流程验收，不自建替代编辑器。 |
| NEXT | 真实来源与扩展验证 | ChEMBL/BindingDB 分别区分在线/本地文件验证；Chrome 中实际加载 MV3 并验证用户主动跳转。仍禁止 Espacenet 自动导航。 |
| 已实现，仍需回归 | 证据引用回跳和当前架构文档 | `f3da90c` 已加入 typed citations/UI 回跳，overview 已整合；跨分页对象定位与真实来源可追溯性按当前验收矩阵检查，不再作为待新建功能。 |
| LATER | >5000 行导出、描图缓存淘汰 | 测量到规模需求后设计持久任务与容量上限；现阶段明确限制，不新增分布式队列。 |
| LATER | 自然语言规划、跨同族比较、SAR 推断 | 真实来源、明确查询契约与证据链验证后独立规划；当前离线摘要不算这些能力已完成。 |
| REJECT | 新仪表盘、并行运行时、完整 Markush/FTO 宣称 | 不服务当前闭环或违反项目边界。 |

## 本轮验证记录（文档复查轮）

- 已检查：Git 状态、规则与设计文件、历史实施/架构记录、上述定向源码。未修改产品代码、迁移、数据夹具或图片。
- `rtk git diff --check`：passed。另用 `rtk proxy python3` 标准库检查本轮 7 份文档的代码围栏、行尾空白、5 个本地链接和所列源码路径：全部 passed（包含尚未跟踪的新计划文件）。
- 未检查：应用启动、浏览器交互、chemistry/API 测试、实时来源与性能。历史 88 项测试结果不冒充本轮结果。
- 本轮变更：AGENTS.md、README.md、PROMPT.md、UI 设计指引、架构概览、M1–M5 实施记录及本计划。

## 修复轮验证记录（2026-09-14，UI-01 至 UI-06）

环境：`docker compose up -d --build`（app + db 均 healthy；healthz ok，dataset demo-fixture-v1）。
前端 `tsc -b && vite build` 通过（主包 ≈249 KB / 77 KB gzip）。测试 `rtk pytest`：**91 通过、0 失败、0 跳过**
（新增 `tests/test_paging_contract.py`：150 条合成夹具的分页/钳制/互斥断言）。Shell 均经 `rtk` 执行。

- 浏览器（in-app browser，对当前 checkout 的 compose 栈）：
  - 1440×900：150 条家族虚拟化成立（DOM 13–14 行、首次仅 46 次描图请求）；结构查询分页条 "1–100 of 150" →
    Load more → "1–150 of 150"；UI-01 关闭中止（旧过滤条未被覆盖）；UI-02 `[Na+]` 命中钠盐记录；
    UI-04 Tab/Shift+Tab 循环与焦点归还；UI-05 `history.back/forward` 恢复两个查询。
  - 1024×800：证据区为 fixed 覆盖层（设计指引<1024 规约）；模态焦点循环全部在面板内。已记录观察：
    覆盖层展开时挡住表头工具按钮，需先关闭抽屉再操作 Save/Export——与覆盖抽屉模式一致，记入 Q&A（UI-OBS-1）。
  - 760×800：结构检索可用且修复后整页无横向溢出（此前 table-header 不换行导致溢出，已修）。
- 截图存于 `docs/plans/ui-round-verification/`（1440 检索分页、[Na+]、1024 覆盖层/模态、760 检索）。
- 分页/虚拟化测量：`benchmarks/paging-measurement-2026-09-14.md`（载荷 89.7 KB/100 行、描图按视口懒加载、
  150 行滚动 ≈1.0 s、堆 ≈163 MB）。历史基线 `benchmarks/m0-baseline.json` 未覆盖。
- 测量后以 `docker compose down -v && up -d --build` 重置数据库并复验：healthz ok、demo 数据正常、
  分页夹具家族已移除（404）。
- 架构 overview 已改写为当前契约（DOC-06 关闭）；已关闭的 M0/M1–M5 计划移入 `docs/archive/` 并更新
  README/PROMPT/overview 指针。
- `rtk git diff --check`：passed（修复轮收尾时复跑）。
