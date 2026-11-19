# 调研汇总：同类工具、治理框架、技术栈标准、规则组合（2026-11-19）

> `readiness-tool` 汇总。四个方向由只读调研子代理完成，原始报告在 [raw/](raw/)，每条事实都在原始报告里标了【原文】（附 URL）、【未核实】或【推断】。
> 主会话用 `gh api` 抽查了 7 个仓库的存在、归档状态、许可证、星数，以及 2 个版本号，全部与原始报告一致（见文末"核对记录"）。
> 已评估过的 Kodus、Luminary、Factory（`tool-evaluation.md`）没有重复调研。

## 0. 结论先说

1. **没有可以直接拿来用的现成工具。** 能借鉴的很多，但没有一个同时做到这几点：尺子是输入、必须项全满足加建议项达到 80%、逐档累进、豁免带到期日、按应用判定、能复检对比。我们自己写是对的，第一轮 Spec 的大方向不变。
2. **关于"要不要按技术栈约束"，社区的答案是基线通用，达成手段按栈给示例。** 跨栈的成文标准都不按语言分级，而是按成熟度或强度分级，包括 OpenSSF 的 OSPS Baseline（L1–L3）、SLSA、Scorecard，以及 Google 的代码评审规范。各栈"公认必有"的东西抽象成结果后高度一致；栈与栈的差别只在用什么手段做到。
3. **但"只写结果"有一个缺口：静态检查。** 例如 TS 的类型检查、Go 的 `go vet`、Rust 的 clippy、Shell 的 ShellCheck，这类要求只有点名具体手段才说得清。所以建议在通用尺子之上**加一层可选的技术栈尺子**，内容以"建议"为主，只有少数条款升为必须。
4. **工具这边要补"尺子分层组合"。** 推荐最简单的一种做法：一份通用尺子加若干技术栈尺子，只叠一层，不做继承链；同一个条款 id 只能在一处定义，其他层只能收紧、不能放宽；要放宽只能由仓库申请豁免。
5. **我们有三处在社区里找不到先例**，分别是复检对比作为正式输出、"建议项满足比例"门槛、"判断题"作为条款字段。这三处就是我们要自己定的部分，也最该写测试。

## 1. 直接回答：通用框架，还是按技术栈约束？

**建议：两者都要，分三层，各层的强度不同。**

| 层 | 内容 | 强度 | 归谁 |
| --- | --- | --- | --- |
| 通用尺子 | 现在 v2.0 的 34 条：GitHub 设置、能力结果、接口入口 | 必须与建议都有 | `autopr-standard` |
| **技术栈尺子（新增）** | 每个栈 3–8 条，主要是"只能点名手段"的静态检查类，外加该栈特有的结果（例如后端的配置外置、数据库迁移、健康检查） | **以建议为主**，只有极少数是必须 | `autopr-standard`（内容），工具负责组合与判定 |
| 达成示例 | 各栈"通常用什么工具做到"，即现在的 `ecosystem/*.md` | 不计分 | `autopr-standard` |

技术栈尺子的候选条款（调研子代理从成文标准中摘出，标 ※ 的是未找到一手出处的推断，详见 [raw/03](raw/03-stack-standards.md) §6.1）：

| 栈 | 适合做"必须"（写成结果） | 只适合"建议" |
| --- | --- | --- |
| 前端 TS/JS | 用了 TS 的，类型检查和构建在 CI 通过 | lint（含可访问性规则）、E2E 冒烟、性能预算、依赖审计 |
| 后端 / 服务 | 配置与密钥外置（12-Factor）；数据库迁移可重复执行、与发布分离※；回滚路径 | 健康检查与优雅关闭、日志 / 指标 / 追踪、API 契约※、分阶段发布 |
| Python | `pyproject.toml` 声明项目与依赖；有锁文件 | 类型检查、lint※ |
| Go | `go.mod` 与 `go.sum` 入库；`go vet` 或等价检查在 CI | `go mod tidy` 无差异、fuzz |
| Rust | `Cargo.lock`（二进制项目）※；`cargo test` 入口 | clippy 警告即失败、`cargo fmt --check` |
| Shell | — | ShellCheck 在 CI（脚本多时升为必须） |

**不建议写成必须的**（调研中各方一致或有明确反思）：覆盖率百分比；具体工具名；Core Web Vitals 数值，因为它是线上真实用户指标，不适合当合并门槛；OSPS 要求"非作者的人工审批"，和我们"只有用户一个人"的前提冲突，不能照搬。

**对本组织的现实意义**：12 个仓库里只有前端（3 个）、Shell 插件（6 个）、内容（2 个）、契约（1 个），没有后端。所以技术栈尺子第一批只需要前端和 Shell 两份；后端、Go、Rust 可以先在格式上留好位置，内容以后再写（要不要预留，见 §5 拷问问题 Q3）。

## 2. 同类工具里值得借的（按 Spec 模块归类）

### 2.1 `clause-format` 条款格式

| 借什么 | 来源 | 怎么用 |
| --- | --- | --- |
| 字段：`na_allowed`、`na_justification_required`、`rationale`（理由）、`future`（预告的条款）、`obsolete`（作废） | OpenSSF Best Practices Badge 的 `criteria.yml` | 补进条款字段。`future` 正好对应标准 §11 的"新增条款 30 天宽限期" |
| 条款级宽限期：`since`（引入版本）、`enforce_from`（生效日期），生效前按建议计、只告警 | 组合机制调研的推断，最接近的是 Semgrep 的"监控 → 评论 → 阻断"渐进模式 | 把标准 §11 的宽限期从文字规则变成格式字段，由脚本计算 |
| 尺子单独成包：带 manifest（规则版本、兼容的引擎协议版本）、用 schema 校验、用夹具仓库做快照测试、加载器拒绝不认识的字段 | `harrydaihaolin/agent-readiness` 及其规则仓库（10 星，无许可证，只借思路） | 我们的 `clauses lint` 加上"兼容的引擎协议版本"检查；尺子自带夹具测试 |
| 规则结构 `level` + `rule{type, options}` + `where`（按条件套用）+ `fix` | TODO Group repolinter（**2026-02-06 已归档**，只借格式） | 和我们的 `levels` + `probe` + `applies` + `remedy` 基本对应，说明方向是对的 |

### 2.2 `probes` / `detect` 检测

| 借什么 | 来源 | 怎么用 |
| --- | --- | --- |
| **"无法判定"不记 0 分，也不从分母里剔除**；N/A 才剔出分母；类别集合固定，以保证不同仓库可比 | `tittle-xyz/toaster-ready`（ok / no-data / not-applicable） | 和我们 A9 的设计一致（`unknown` 按不满足计但单列），佐证了这个选择 |
| **权限不够时判 UNKNOWN，不判 FAIL**：只要规则集里有 bypass 名单，Scorecard 就判"对管理员不生效"；非管理员 token 读不到部分分支保护设置；也读不到仓库的 workflow 默认只读开关 | OpenSSF Scorecard 的 Branch-Protection、Token-Permissions | **直接影响 G2、G6 的探针**：要先判断 token 权限够不够，不够就是 `unknown`。这是继 pwa-platform 之后的第二类误判场景，要做夹具 |
| 结果枚举 PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NEEDS_REVIEW，外加未评估条款清单（`notEvaluated`）和 `evidence[]` | Scorecard 的 conformance 模式（实验性） | `NEEDS_REVIEW` 对应我们"待 agent 裁决"的条款；报告里加未评估清单 |
| 技术栈检测只给提议，以仓库显式声明为准；报告里打印"检测到了什么、依据哪些文件" | Renovate（`enabledManagers`）、Semgrep、CodeQL | 仓库在 `readiness.yml` 里写 `stacks`，就跳过自动检测 |
| 适用范围用 `match` + `exclude`：字段之间是"且"，列表之内是"或"，`exclude` 优先 | Kyverno | `applies` 的语义照此写死 |

**Scorecard 要不要直接复用**：它很活跃（v5.7.0，Apache-2.0），判据也成熟；但它是 Go 二进制，复用会破坏零依赖。总分是按风险加权的 0–10 分，会掩盖单项缺失，不适合当门槛。**建议只借判据，不依赖它**；如果本机装了 Scorecard，也可以作为可选的外部探针输入。

### 2.3 `report` / `recheck` 报告与复检

| 借什么 | 来源 | 怎么用 |
| --- | --- | --- |
| JSON 字段"只增不删"的兼容承诺 | `paladini/harness-score`（632 星，MIT） | 写进三份格式的版本规则 |
| 退出码 2 表示"扫描不完整" | harness-score | 和我们的 2（调用或配置错误）语义不同。建议保持与接口层契约一致：2 是配置错误，3 是环境未就绪；"扫描不完整"用报告里的 `unknown` 计数表达，不另占退出码 |
| `--baseline`、`--fail-below`、SARIF 输出 | harrydaihaolin/agent-readiness | `--baseline` 已有；SARIF 先不做，没有消费者 |
| 掉档原因单列，例如"豁免过期导致掉档" | 治理框架调研的建议 | `diff` 输出里给每个档位变化标原因类别：仓库变化、尺子变化、豁免过期、声明过期 |

### 2.4 `remedy` 修复

| 借什么 | 来源 | 怎么用 |
| --- | --- | --- |
| 修复先 dry-run，再执行 | `ambient-code/agentready`（157 星，MIT）的 `align` | 和我们"只出补丁"一致 |
| 修复后自动复评 | `0xmariowu/AgentLint`（67 星，MIT） | 对应 `remedy` 验收里的"补丁应用后复检该条 met" |
| 豁免状态机：待批准 → 已批准 → 已拒绝 / 已撤销 → 已过期，过期后恢复正常判定 | Cortex（商业产品，只借思路） | 我们的豁免只认"已批准"和"已过期"两个状态就够了（只有用户一个人批准） |

## 3. 坑（调研里反复出现的）

1. **分数不可比、权重主观**：加权总分会掩盖关键项缺失（Scorecard、harness-score 都有这个问题）。我们用"必须项全满足"加"建议项比例"，不用总分，这是对的。
2. **纯 LLM 判定不稳定，还费 token**：superduck、Factory 都是这类。我们把模型限制在判断题上，且以上一份报告为基准，这是对的。
3. **规则和引擎分在两个仓库，联动维护成本高**（harrydaihaolin 的教训）。我们的尺子由 `autopr-standard` 维护，放在哪个仓库要和对方定（接口清单 #1、#7）。
4. **权限不够就会误判**（见 §2.2 Scorecard 那条）。
5. **同类工具大多评的是"配置成熟度"，不覆盖"能不能放心自动合并"**。这正是 v2.0 里 P、K、R、X 四个专有支柱存在的原因。

## 4. 对 Spec 的影响（待你确认后再改，现在没动）

| # | 改动 | 涉及 |
| --- | --- | --- |
| S1 | 条款文件分 `kind: base` 和 `kind: stack`；仓库按 `stacks` 声明（或自动检测）组合一份通用尺子和若干技术栈尺子；只叠一层；同一个 id 只能在一处定义；其他层只能通过 `tighten` 收紧档位和强度，**不能改适用范围，不能放宽，也不能删除** | `clause-format`、`detect` |
| S2 | 条款增加字段：`na_allowed`、`na_justification_required`、`rationale`、`since`、`enforce_from`、`status: active / future / obsolete` | `clause-format` |
| S3 | monorepo 的应用可以各自声明技术栈，例如 `apps.site.stacks: [frontend]` | `clause-format`、`detect` |
| S4 | 探针先判断 token 权限够不够，不够就判 `unknown`；为 G2 补"规则集带 bypass 名单""非管理员 token"两类夹具 | `probes` |
| S5 | 报告增加未评估清单，以及每个档位变化的原因类别 | `report`、`recheck` |
| S6 | 三份格式都承诺"字段只增不删，改语义就升主版本" | §3 |
| S7 | 跨会话接口清单新增一条：技术栈尺子的内容（第一批前端、Shell）由 `autopr-standard` 写，格式由我定 | §11 |

## 5. 拷问问题（调研后更新，接下来一次问一个）

| # | 问题 | 为什么要问 |
| --- | --- | --- |
| Q1 | 技术栈尺子的定位：**只做建议层**（不影响能不能接入），还是允许少数条款升为必须（例如"用了 TS 就必须类型检查通过"）？ | 这决定了换一个栈会不会被卡档，也决定了 `autopr-standard` 要写多少内容 |
| Q2 | 这个工具只服务本组织的 12 个仓库，还是将来要给组织外的人用？ | 决定格式要做到多通用、要不要考虑 GitHub 以外的平台、文档写给谁看 |
| Q3 | 本组织现在没有后端项目。后端、Go、Rust 这些技术栈尺子，现在只在格式上留位置，还是第一批就写内容？ | 写内容要 `autopr-standard` 投入，而且没有试点仓库来验证 |
| Q4 | "治理成功"以什么为准：报告准、补丁能直接用，还是仓库真的接进了 Auto PR？ | 决定第一阶段的验收线画在哪 |
| Q5 | 技术栈自动检测出错时，以谁为准？我建议以仓库显式声明为准，检测结果只做提示 | 涉及误判由谁兜底 |

## 核对记录（主会话，2026-11-19，`gh api repos/<o>/<r>`）

| 仓库 | 归档 | 星 | 许可证 | 最近推送 |
| --- | --- | --- | --- | --- |
| todogroup/repolinter | **是** | 467 | Apache-2.0 | 2026-02-06（最新 release v0.12.0） |
| ossf/scorecard | 否 | 5846 | Apache-2.0 | 2026-11-19（最新 release v5.7.0） |
| harrydaihaolin/agent-readiness | 否 | 10 | **无** | 2026-07-21 |
| ambient-code/agentready | 否 | 157 | MIT | 2026-11-18 |
| paladini/harness-score | 否 | 632 | MIT | 2026-11-17 |
| 0xmariowu/AgentLint | 否 | 67 | MIT | 2026-11-13 |
| tittle-xyz/toaster-ready | 否 | 3 | Apache-2.0 | 2026-09-15 |

没有核对的：Scorecard 对规则集 bypass 的具体判法、Best Practices Badge 的字段名、Cortex 豁免状态机。这三条在 §2 里直接影响设计，改 Spec 前我会再打开原文核一次。
