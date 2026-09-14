# 简洁 LLM 接口计划

日期：2026-09-14。基线：`6c33eea`。状态：下一轮执行提案，尚未实施。
分类：CORE（现有摘要闭环的真实模型接入）。目标：配置一个模型端点，在现有 AI 标签中生成可追溯的同族摘要；保持无模型配置时的离线使用路径。

## 1. Q&A：当前事实与更新核对

| 问题 | 核对结果 |
| --- | --- |
| 最新更新是什么？ | `6c33eea` 添加结构请求 AbortSignal、服务端分页信息、模态 Tab 循环、URL push/popstate、分页测试和验证图片，旧 M0/M1–M5 记录已归档。 |
| 本轮实际验证了什么？ | 前端 TypeScript noEmit 检查通过；chemistry 与离线 planner 共 10 项测试通过。未重跑 PostgreSQL 集成、浏览器或历史 91 项全套测试。源码存在不等于所有场景再次验收。 |
| 是否完全没有 AI 接口？ | 已有 `services/core/spago_core/services/ai.py` 中的 SummaryProvider/OfflineExtractiveProvider，已有 POST family summary、POST ai/plan、ai_analyses 表和 EvidencePanel 的 AI 标签。缺少 HTTP 模型适配器、配置、可用状态及真实推断的引用闭环。 |
| 是否要引入 agent 框架或代理服务？ | 不需要。现有 httpx、Pydantic、FastAPI、PostgreSQL 已满足单次摘要需求。 |
| 配置放在哪里？ | 首期复用服务器环境配置；浏览器只显示脱敏状态，不保存密钥。当前没有管理员身份/配置权限层，增加可写密钥 UI 会扩大范围。 |
| 第一版做自由聊天吗？ | 不做。只总结当前同族已选取的事实；自然语言查询、会话、工具执行独立后续规划，现有 ai/plan 的确定性行为保留。 |

接模型前必须处理的既有问题（本轮源码发现，尚未修复）：

- **LLM-01 / P1，引用误关联**：`_collect_family_facts` 以 `e.compound_id = c.id` 连接测量与证据。某化合物在专利中出现，并不能证明其某条活性测量来自该专利；重复 mention 还会放大结果。禁止把这些 join 产物直接送模型当测量证据。
- **LLM-02 / P1，缓存与持久化不一致**：当前先生成再查重；analysis_id 只考虑 provider、family、一个版本及记录数量，数值/模型变化可能不换 ID。冲突时保留旧数据库行，却返回新 text 和旧 created_at；接收费接口后还会重复调用。
- **LLM-03 / P1，AI 上下文失效**：AiTab 未传 AbortSignal、未按 family 复位结果，只显示引用数量。慢响应可落入已变化的界面；需复用结构查询的作废思想，但判断当前 request/family，不能只检查旧闭包捕获的值。
- **LLM-04 / P2，范围与统计**：当前 scaffold 按 mention 数计数，issues 为全库计数，measurement_count 粒度不足，dataset_version 取任意文档；提示词还硬编码 synthetic。先明确各项统计粒度、范围、真实来源模式和多版本清单。

## 2. 参考项目：只借鉴必要部分

参考对象为本地自建项目 CursorSwitch（`/media/chen/Machine_Disk/ClaudeSci/CursorSwitch`，基于 ccswitch 演进；初稿曾误记为仅公开 GitHub README，实施前已按用户更正直接核对其源码）。本项目只借鉴三项配置（baseURL/apiKey/modelID）和清晰的 provider 边界；模型发现、自动回退/故障转移队列、路由链、本地代理与请求改写、账号/授权绑定、用量脚本注入、计费仪表盘均不纳入。

已从源码核对（`src/types.ts`、`src/config/*ProviderPresets.ts` 及其测试，2026-09-14）：
- base_url 惯例为**包含完整 API 前缀（含版本段，如 `…/zen/go/v1`）的根路径**，调用侧只追加 `/chat/completions`
  （其 preset 测试即断言 `` `${base_url}/chat/completions` ``）。SPAgo 沿用同一惯例，与初稿计划一致，无需修改。
- 该项目另设 `isFullUrl`（视为完整端点不拼路径）、`apiFormat`（anthropic/openai_chat/openai_responses/gemini_native）
  与故障转移队列等扩展。SPAgo 首期协议子集固定追加 `/chat/completions`，不需要这些开关；仍列入 §10 后置/拒绝。

[Ollama 官方兼容说明](https://docs.ollama.com/api/openai-compatibility) 提供 `/v1/chat/completions`，同时明确只是部分 OpenAI API 兼容。这支持选择一个小的共同协议子集，而不是承诺兼容所有厂商和模型。以上来源访问日期为 2026-09-14；具体接入目标必须通过契约测试和显式 live smoke。

## 3. 唯一调用路径

```text
现有 AI 标签：用户点击生成
  → POST /api/v1/families/{id}/summary
  → ai.py：收集有界事实 → 内容缓存 → 调用 provider → 校验引用 → 保存
  → OfflineExtractiveProvider 或 OpenAICompatibleSummaryProvider
  → 现有 ai_analyses 表
  → 返回摘要、来源标签和可点击引用
```

新增一个内部 adapter 文件即可：`services/core/spago_core/adapters/llm.py`。沿用 SummaryProvider 的职责，统一小型结果对象（文本段落、引用、可选 token 用量）；不要建立 provider registry、插件系统、通用 agent runtime 或第二套数据库。

现有同步 FastAPI 路由可先保留，使用同步 httpx.Client、有限超时和并发上限；不要将整个服务改成 async。请求作废满足首期需求：浏览器离开后忽略结果，后台调用受 deadline 限制并可保存已完成缓存；界面不得宣称供应商已取消或停止计费。

## 4. 配置与最小协议

日常只配置三项，沿用 `SPAGO_` 前缀：

```dotenv
# 模板中的域名和模型名仅是占位，不是默认外发目标。
SPAGO_LLM_BASE_URL=https://provider.example/v1
SPAGO_LLM_API_KEY=
SPAGO_LLM_MODEL=your-model-id
```

- 未配置 base URL/model：离线可用；只配置其中一项：LLM 配置不完整，其他功能照常。
- api_key 用 SecretStr；无鉴权本地端点允许留空，留空不发 Authorization。配置只在后端读取，Compose 必须显式传入三项，修改配置后重启 app 生效。不能误认为 Compose 自动将所有 `.env` 变量注入容器。
- base URL 是包含完整 API 前缀的根路径；去尾斜杠后只追加 `/chat/completions`，不重复追加 `/v1`，不探测多个地址。拒绝含 userinfo、query、fragment 的地址。默认 HTTPS；明确配置的本机/受信任内网 HTTP 端点允许用于本地部署，不接受用户请求覆盖目标 URL/headers。
- 容器内 localhost 指向容器自身；文档分别给出容器服务 DNS 和显式配置的宿主机连通方式，不默认添加任何本地模型服务。无需 key 的本地服务不应附带另一个供应商的 key。
- 首期固定一个活动端点、一个模型，手工填写 model ID；不新增模型列表 API，不自动切换 provider/模型。
- 出站只发 `model`、`messages`、`stream: false`、`max_tokens`。首期支持接受这些字段并返回文本 choices 的 Chat Completions 子集；不声称覆盖 Responses-only、原生 Anthropic、所有 reasoning 模型。400 参数不兼容时直接说明，不自动改协议/删除预算限制重发。
- 不默认注入 temperature、工具定义、response_format、自定义任意请求体。输出通过提示要求 JSON 并用 Pydantic 校验；不合法则失败，不用第二次 LLM“修复”请求。

内部默认预算：连接 5 秒、单请求总 deadline 60 秒（结合 httpx 分阶段超时与有界读取；read timeout 本身不是总 deadline）；输入选取最多 50 个事实且序列化正文 ≤32 KiB，每条摘录 ≤1 KiB；输出上限 1500 tokens，HTTP 响应 ≤256 KiB。裁剪只移除完整条目并返回 included/omitted/truncated，不能切断 JSON、结构或测量值，也不能把字节上限说成精确 token 数。模型上下文太小时明确失败。

首期单进程最多 2 个模型调用；同一内容键在执行时返回已在处理（409），其余超过并发上限返回 busy（429），无持久队列。用有界的在途键集合/锁，finally 清理。多 worker/副本不在此并发保证内，部署文档明确单 worker；真有扩容需求再引入数据库 job 协调。

重试策略为**自动重试 0 次**：昂贵生成请求在读超时后是否已计费未知，用户看到错误后可手动重试；错误/半截输出不缓存、不回退到离线伪装成功。429 保留经过校验的 Retry-After，不自动重新生成。记录耗时和供应商返回的 usage；缺 usage 为 null，不估算成“真实成本”。

## 5. API 与 UI 兼容契约

| 接口 | 约定 |
| --- | --- |
| 新增 `GET /api/v1/ai/status` | 本地读取配置，返回 offline/configured/config_invalid、model、脱敏目标标识、reason；configured 只代表配置齐备，不代表在线验证通过。无供应商调用、不返回 key 或完整含内部路径的 URL。 |
| 现有 `POST /families/{id}/summary` | 请求体可选 `{ "mode": "offline" | "llm" }`，缺省保持 offline，旧调用不意外产生付费请求。llm 未配置返回 503；现有未知同族 404 保留。 |
| 响应 | 保留 analysis_id/provider/provenance_state/text/citations/dataset_version/created_at；新增可选 model、cached、usage、coverage。离线 machine_extracted；所有 LLM 叙述 llm_inferred。多版本完整信息在 coverage/input snapshot，旧 dataset_version 字段多版本时明确标为 mixed。 |
| 错误 | 502：上游鉴权/模型不支持/响应或引用校验失败；504：超时；503：未配置；409：同内容执行中；429：忙或上游限流。沿用项目 ApiError 的 detail 文本路径，客户端不必先重构错误框架。错误脱敏，不回显上游原始请求/响应。 |

首期不新增通用 chat、配置写入、模型发现、连接测试接口。首次显式生成就是该模型实际可用性的检查；不要以 `/models` 可访问冒充生成成功。

AI 标签内保留一个“生成摘要”主操作：顶部显示“离线摘要 / LLM 摘要”紧凑选择（仅已配置时可选 LLM），当前模型、同族范围和“发送所选来源记录”的提示；不是当前化合物或全部 PDF。生成期间显示等待与停止等待；状态变化、关闭、切换 family 后以 AbortSignal + 当前请求标识作废旧响应。已缓存结果显示复用，首期不提供强制刷新按钮，避免当前 Regenerate summary 语义与缓存冲突。

现有 EvidencePanel 的 compound/occurrence 来源标签只在 Evidence 视图显示；AI 视图显式展示 family 和分析 provenance，避免把上方 Machine extracted 标签误解为 LLM 结论的属性。引用可跳转到现有证据区或测量详情；找不到原始出处时说明只链接数据库记录。纯文本渲染，无 HTML 执行。

配置 UI 暂不做：首期部署者编辑环境配置，使用者在 AI 标签看状态并调用。未来若确需在界面填写地址/密钥/模型，先定义管理员权限和密钥存储，复用一个按需弹窗，不增加永久 Settings 面板。本轮不引入用户系统。

当前 Compose 对外发布 app 端口；启用服务器付费 key 的支持路径先将 app 端口默认绑定 `127.0.0.1`。LAN/托管使用须通过已有或部署侧认证入口，再显式开放，不把 CORS 当认证。配置管理及无凭据调用的离线模式不因模型失败而失效。

## 6. 先修证据输入，再接生成

1. 按 family/document/compound 关系选取事实，统计使用明确 DISTINCT 粒度；全局 ingestion issues 不放进同族结论。计数在 SQL 端聚合，具体事实按稳定排序和 LIMIT 选取，不能先把整族测量 `.all()` 到内存后截断。未能确定所属范围的数据排除并报告缺口。
2. 测量以 measurement.id 唯一标识，携带 assay、relation、value、unit、source_record_id、source_name、dataset_version、provenance。它是数据库测量记录引用，不能因同一 compound 就标成专利原文证据。缺直接关联时不填 evidence_id；无需为首期虚构或批量回填关系。
3. 证据摘录、测量记录、同族汇总使用带类型的 fact_ref（如 evidence/measurement/family 加稳定 ID），由服务端建立允许引用集合；引用保存快照并回跳对应对象。保留旧 evidence_id/inchikey 字段用于旧引用，新增引用是明确的类型分支，不把 measurement.id 塞进 evidence_id。
4. 模型返回 `{"paragraphs":[{"text":"…","fact_refs":["…"]}],"limitations":["…"]}`。限制段数、文字长度和 refs；非空事实段必须引用输入允许集合。未知/跨范围引用、缺引用、tool_calls、空文本、非正常结束或半截输出均拒绝，不持久化为成功。
5. 引用集合合法只能证明指向存在，不能证明句子被来源支持；LLM 输出始终标推断，显示“需核对原文”。服务端不采用模型输出覆盖结构、测量、target 或 claims；数值事实展示复用记录本身，不把生成文本当结构化数据入库。不同 assay 不计算自动选择性，缺活性不判无活性，无证据不生成确定法律结论。
6. 专利摘录与所有来源内容是待分析数据，固定指令和输入分开；不提供工具执行或任意 URL 抓取。仅发送限定事实，不发送数据库凭据、API key、完整 PDF、完整 bulk 数据或客户端任意上下文。

## 7. 内容缓存与迁移

复用 ai_analyses，不建立聊天表。新增一份前向 SQL 迁移（实施时取下一个序号，当前应为 0006），添加 nullable 的 `model`、`input_hash`、`prompt_version`、`input_snapshot` JSONB、`usage` JSONB。snapshot 仅包含本次有界科学事实、来源版本和 coverage，不保存密钥、传输 headers、原始 provider body 或隐藏推理。

缓存键使用规范化 JSON 的 SHA-256：精确输入快照 + family + mode/provider + model + 脱敏端点配置指纹 + prompt_version + 输出预算。端点指纹不含 key；换同端点 key 不使科学结果失效。排序稳定；不能只 hash 记录数量。读取成功缓存必须在调用模型前发生；生成、校验后写入，返回最终持久化行；冲突也返回数据库中的胜出记录，禁止新文本配旧时间。DB 事务不横跨外部 HTTP 等待。

旧记录原样可读，但 input_hash 缺失时不作为新协议缓存命中；新离线 provider 与 LLM 使用不同键和来源状态。迁移从 0005 可前向执行，关闭 LLM 配置可回到离线路径，无需破坏性回滚数据。

## 8. 分步执行与验证

| 顺序 | 修改范围 | 验收重点 |
| --- | --- | --- |
| A：输入与缓存 | ai.py、现有 M5 tests、一个新增迁移；必要的 typed models | 同化合物不同来源/assay 不串引用；不同记录数量相同但值变化仍换缓存；重复请求不重复生成；数据库与返回一致。先离线验证。 |
| B：配置与适配器 | config.py、adapters/llm.py、main.py 生命周期、.env.example、Compose | 复用 httpx；正常/无 key 本地端点、路径拼接、重定向、401/429/500、超时、超大/坏 JSON、usage 缺失、并发清理；MockTransport 默认零外网。 |
| C：接口与原 AI 标签 | routes.py、api/types.ts、api/client.ts、EvidencePanel.tsx；引用回跳必要时触及 App.tsx | 旧无 body 调用仍离线；配置状态准确；显式 LLM 调用；空/错引用拒绝；关闭/换 family 不污染结果；可点击来源。无新增导航。 |
| D：集成与记录 | 现有 tests、README、overview、设计指引、当前计划 | 前向迁移、离线回归、真实模型 smoke、浏览器及预算测量；完成后更新手册和缺口。 |

真实 smoke 仅在部署者已配置并明确使用该端点时运行一次，使用最小合成事实，记录目标模型、耗时、usage（若返回）、缓存复用、错误/来源状态；密钥不进日志。没有凭据时此项记 not checked，不能用 mock 宣称 LLM 已连接。本轮计划阶段不读取真实 key，也不调用收费模型。

浏览器验证既有工作台不受影响，覆盖 1440×900 和 760px：未配置、配置不完整、生成成功、错误、停止等待、切换同族、引用回跳；当前 checkout 服务和截图可追溯。测量有界输入字节、一次调用耗时、输出字节、cache hit 的外部调用数=0、并发上限，不承诺未测得的延迟改善。

## 9. 本轮更新检查的剩余项

- **UI-07 / P1（源码确认，未浏览器复现）**：普通列表 Load more 仍只是将 limit 加到 500，没有 offset；>500 个化合物时后续记录不可达。下一次 UI 修复应使用真正分页，不能将 150 条夹具通过视为覆盖此边界。独立于首期同族摘要接口，不从前端已加载行收集模型上下文。
- **UI-08 / P2（源码确认）**：结构 Load more 的 catch 静默吞错；保留已加载行同时应显示可重试错误。不要复制此模式到 LLM 错误处理。
- 旧 UI 计划的已修复记录保留为历史；本轮不是全量再次验收，缺口不因旧计划写“完成”而消失。

## 10. 明确后置

NEXT：需要时增加原生 Anthropic/Responses 适配器或管理员配置弹窗；每次只增加被真实端点证明必要的协议差异。LATER：流式输出、多模型配置、模型发现、自由聊天、工具调用、自然语言 planner、费用面板。REJECT：自动模型回退、复制 Cursor 代理/账号逻辑、独立网关、第二运行时、为了一个摘要引入 LangChain/LiteLLM/向量库。

完成标准：三项环境配置能跑通一个已验证模型；旧离线路径兼容；事实和引用校验、内容缓存、错误/等待状态可测试；Docker 用户无需额外服务。代码体积不是唯一标准，但任何新增层都必须服务上面的一条验收。

## 实施验证记录（2026-09-14，步骤 A–D 完成）

环境：`docker compose up -d --build`（app+db healthy）；前端 Node 22 `tsc -b && vite build` 通过；
后端 `rtk pytest`（services/core）：**125 通过、0 失败、0 跳过**（新增 `tests/test_llm_adapter.py` 23 项、
`tests/test_llm_concurrency.py` 1 项；`tests/test_m5_ai.py` 更新为 typed citations/content-key 断言）。
Shell 均经 `rtk`。基线 `6c33eea` 之后本仓库另有 1 次提交（UI 修复轮）。

### A：输入与缓存
- LLM-01 修复：测量引用为 `measurement:{id}` 数据库记录引用，不再 join evidence_records；
  引用校验拒绝未知/跨范围 ref（单测覆盖 unknown-ref 拒绝）。
- LLM-02 修复：`input_hash` = SHA-256(规范化 JSON：input snapshot + family + mode/provider + model +
  脱敏端点指纹 + prompt_version + 输出预算)；缓存查询先于 provider 调用；成功才落库；
  并发冲突返回库中胜出行。测试：数值 +1 → 新 analysis_id/新行；重复请求 cached=true 且行数不增。
- LLM-04 修复：scaffold 按 DISTINCT 化合物计数；全局 ingestion issues 不进入同族摘要；
  dataset_version 多版本标为 "mixed"（coverage 列表携带每版本 synthetic/docs/compounds/measurements）。

### B：配置与适配器
- `config.py`：`SPAGO_LLM_BASE_URL/LLM_API_KEY(SecretStr)/LLM_MODEL`；`adapters/llm.py`：
  URL 规则（拒绝 userinfo/query/fragment；公网 http 拒绝；loopback/私网/`host.docker.internal` 允许）、
  只追加 `/chat/completions`、只发 model/messages/stream/max_tokens、无 key 不发 Authorization、
  不跟随重定向、256 KiB 响应上限、5 s 连接/60 s 总 deadline、usage 缺失为 null、零自动重试。
- `main.py` lifespan 管理共享 httpx.Client。MockTransport 契约测试 23 项：正常/无 key/路径拼接/401/429
  (Retry-After 透出)/500/400 协议不匹配/超时/超大响应/坏 JSON/空内容/tool_calls/非正常结束/重定向不跟随。

### C：接口与 AI 标签
- `GET /api/v1/ai/status`：offline / configured / config_invalid(+reason) 三态；不调用供应商、不回显 key。
- `POST /families/{id}/summary`：无 body 仍离线；`{"mode":"llm"}` 未配置返回 503；409 同内容在途、
  429 超并发上限（进程内有界集合，finally 清理）；502/504 映射上游鉴权/校验/超时；detail 用实例消息。
- AI 标签：同族范围行、模式选择（LLM 未配置禁用）、模型与脱敏目标、Stop waiting（客户端中止，
  文案明确不表示供应商已停止计费）、同族切换重置、typed citations 可点击回跳（measurement →
  打开 Bioactivity；evidence → Evidence 视图）、纯文本渲染、缓存命中标记 "cached" 且无强制刷新按钮。
  Evidence 视图保留化合物/出现位置来源标签；AI 视图显示同族范围与分析 provenance。

### D：集成与浏览器验证（对当前 checkout 的 compose 栈）
- 前向迁移 0006 从零应用通过（compose 启动日志 + schema 检查）；离线路径回归通过。
- 本地 mock 端点（`scripts/mock_llm_endpoint.py`，127.0.0.1/0.0.0.0:8101）+ `host.docker.internal` 配置：
  - 浏览器（1440×900，当前 checkout 服务）：configured 状态、LLM 模式生成成功（chip "LLM inferred ·
    llm-openai-compatible · mock-model"、typed measurement 引用 3 条）、缓存命中（外部调用 0，经 mock 日志
    行数核对）、引用回跳（Evidence 视图 + Bioactivity 展开）、切换同族后摘要重置；
    mock-error → 502 错误条且不落结果；mock-timeout → Stop waiting 中止、无结果、可再次生成。
  - 测量：input snapshot 6,744 B（≤32 KiB）；mock 单次调用 usage prompt=1708/completion=151 tokens；
    缓存命中外部调用数=0；进程并发上限行为=409/429（测试断言）。
  - 未配置 / 只配一半 / 配置完成 三种状态均经浏览器+API 复核（config_invalid 界面给出缺失项原因，
    LLM 单选禁用；半配置下 llm 摘要 503）。
- 截图：`docs/plans/ui-round-verification/llm-mock-cached-1440.png`、`llm-error-502-1440.png`、
  `llm-stop-waiting-1440.png`。验证后已 `down -v` 重置并复归未配置离线部署（healthz ok）。

### 未检查 / 缺口（诚实记录）
- **真实模型 smoke：not checked**（本环境无任何供应商凭据；未调用收费模型）。部署者配置真实端点后的
  首次生成即为该检查；mock 无法证明真实供应商的协议兼容性。
- UI-07（普通列表 >500 行需真正 offset 分页）与 UI-08（结构 Load more 静默吞错）仍开放，按其优先级
  排入下一轮 UI 修复；本轮未触碰。
- 多 worker/副本部署不在进程内并发保证内（单 worker 为当前部署前提，已在文档说明）。

## 本轮检查记录

- 在 `apps/web` 执行 `rtk proxy /home/chen/.nvm/versions/node/v22.22.0/bin/node node_modules/typescript/bin/tsc -p tsconfig.app.json --noEmit`：passed，无产物写入。
- 在 `services/core` 执行 `rtk proxy .venv/bin/python -m pytest tests/test_chemistry.py tests/test_m5_ai.py::TestPlanner -q`：10 passed。此选择未调用创建/删除 scratch DB 的集成 fixture，未更改运行数据库。
- `rtk git diff --check`：passed；Python 标准库检查 4 份本轮文档的代码围栏、行尾空白和本地链接目标：passed。
- 只修改计划、设计指引与交接指针；没有实现 LLM adapter，没有修改产品代码或引入依赖，没有 live 模型调用。下一轮执行者须核对届时 HEAD 和迁移序号。
