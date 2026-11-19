# 调研 01：AI / agent 就绪度类工具（不含 Kodus / Luminary / Factory）

调研日期 2026-11-19。只读调研，未安装、未运行任何被调研工具。
标注说明：【原文】= 我用 `gh api repos/<o>/<r>`（元数据、README、文件树、文件内容）或 WebSearch 结果打开/读到的一手内容，URL 见文末；【未核实】= 只在搜索摘要或二手页面看到；【推断】= 我据原文推出的判断。星数与最近提交日期均为 2026-11-19 当天 `gh api` 查得。

## 结论先说

1. 同类工具已经很多（本次找到 10 个值得看的），但**几乎都是"引擎 + 内置规则写死在代码里"**；只有 `harrydaihaolin/agent-readiness` 把规则拆成独立 YAML 规则包仓库（`agent-readiness-rules`），这是最接近 repo-readiness"尺子与引擎分离"的先例。
2. **"确定性扫描 + 判断题交给 agent"的三段式在现有工具里只出现雏形**：toaster-ready（核心确定性、可选 skill 层加判断）、AgentLint（51 条确定性 + 7 条 opt-in 的 AI 子 agent 检查）、superduck（全靠 subagent 读 md 条款，非确定性）。没有一个把"哪些条款是判断题"做成条款文件里的显式字段并由脚本最终打分。
3. **按技术栈区分条款的做法很浅**：多数是"同一条款内部多语言分支"（superduck、harrydaihaolin 规则里的 glob 并集）或"`is_applicable()` 返回 False 则跳过"（ambient-code）；没见到按"前端/后端"分条款集的。
4. N/A 机制普遍有且重要：toaster-ready 的三态信号（ok / no-data / not-applicable，no-data 绝不记 0，N/A 从分母剔除并重分配权重）、Exadel 的 archetype 导致的 N/A 与分母扣减，是最值得抄的。
5. 最大的坑：各工具分数互不可比、权重多为作者主观；无退出码语义、无机器可读输出的纯 skill/prompt 型工具（Exadel）难以接 CI。

## 对比表

| 工具 | 形态 | 许可证 | 星数 / 最近提交 | 条款数与分层 | 判定是否确定性 / 调 LLM | 机器可读输出 + 退出码 | 修复 | 尺子与引擎分离 |
|---|---|---|---|---|---|---|---|---|
| ambient-code/agentready | Python CLI + 容器 + HTML/MD 报告 | MIT | 157 / 2026-11-18 | 默认权重文件写"30 个 attribute"；4 档 Tier（55/27/14/4%）；认证 Platinum~Bronze | 评估器是 Python 代码，确定性为主；LLM 使用【未核实】 | 有 JSON/HTML/MD、schema 版本化；退出码【未核实】 | 有 `align` 命令（自动修复，含 `--dry-run`） | 部分：权重在 `default-weights.yaml` + 用户 `.agentready-config.yaml` 可调；条款本身在代码里 |
| harrydaihaolin/agent-readiness（+ -rules） | Python CLI + Claude Code 插件 + MCP + GitHub Action + pre-commit | 引擎仓库 README 页未标许可证（API 返回 null）；规则包 MIT | 10 / 2026-07-21；规则包 1 / 2026-11-15 | 4 支柱（认知负载/反馈环/流/安全）+ workspace 协调；规则 YAML 每条带 weight、severity、confidence | 静态扫描确定性；`--run` 在 Docker 里真跑测试；规则文件含 `fix_prompt` 交给 agent | `--json`、`--sarif`、`--fail-below N`（exit 1）、`--baseline` 对比、badge | `apply-top-action` + 规则内 `fix_template`/`action`/`verify` | **是**（规则包独立仓库 + manifest + schema 版本，最像我们） |
| 0xmariowu/AgentLint | npm CLI + Claude Code 插件（`/al`） | MIT | 67 / 2026-11-13 | 51 条确定性（6 维度）+ 7 条 opt-in 扩展（Deep/Session，用 AI 子 agent 和本地会话日志） | 核心确定性；扩展项用 AI | HTML 报告；JSON/退出码【未核实】 | 有：fix plan 分 guided/assisted，修后复评分 | 否（【未核实】标准证据在 `standards/evidence.json`） |
| paladini/harness-score | npm CLI + GitHub Action + badge | MIT | 632 / 2026-11-17 | 108 分、6 维度、36 条；L0–L4 成熟度，等级按 harness"形状"设门槛，不只看总分 | 零 LLM、零网络、同 commit 同分 | `--json`；退出码 0 通过 / 1 门禁失败 / 2 用法错误或扫描不完整；JSON 字段只在 minor 加 | 诊断为主：每个失败项指向配方 | 否 |
| tittle-xyz/toaster-ready | Go CLI（`toaster`）+ 可选 skill 层 | Apache-2.0 | 3 / 2026-09-15 | 11 个加权类别，0–100，三档 band | 核心"确定性、纯函数、评分路径无 LLM"；判断题放可选 skill 层 | JSON 带引用/出处；`toaster gate --min N` 非零退出 | 报告给修复命令；skill 层持久化 | 部分：`.toaster-ready.yml` 可改权重/禁用类别/语言提示；类别集合固定 |
| exadel-inc/agentic-readiness-assessment | Claude Code / Codex / Cursor 等通用插件（2 个 skill） | Apache-2.0 | 25 / 2026-11-09 | 14 个区域加权，满分 105，按 archetype 标 N/A 扣分母；3 个 gate；Ready/Partially/Not ready + 置信度 | **纯 LLM 执行 prompt**，但要求跑安全命令并记录证据；做一次可逆"探针编辑"再还原 | 只写 `reports/agentic-readiness.md`（13 个固定章节）；无 JSON、无退出码 | 输出按 P0/P1 排序的修复清单，不自动改 | 否（规则在 SKILL.md） |
| superduck-ai/agent-readiness | skill（Node 打包 CLI + 9 个条款 md） | MIT | 37 / 2026-06-11 | 82 条 / 9 类；Level 1–4 + App/Repo scope + [Skippable] 标记 | 由并行 subagent 读 md 条款判定，非确定性；CLI 只做第 4–5 步打分/报告 | JSON 报告 + score JSON + HTML；历史快照 | 无 | **半分离**：`criteria/*.md` 是尺子，`bin/*.mjs` 是引擎 |
| markmishaev76/ai-harness-scorecard | Python CLI + GitHub Action + badge | MIT | 21 / 2026-11-16 | 5 类 32 条，A–F 等级 | 【推断】确定性（未见 LLM 说明） | `--format json`；退出码【未核实】 | 无 | 否 |
| Capta1nRaj/goshipit | Agent Skill（npx 安装到 10 个工具） | Apache-2.0 | 34 / 2026-11-18 | 210 条 / 15 类，用户可在 `goshipit.md` 里勾选/取消 | LLM sub-agent 执行（README 自带"耗 token"警告） | `prelaunch-report.md`；无 JSON 说明 | 报告含修复步骤 | 是的一种：`goshipit.md` 是可勾选的检查清单 |
| 其他（只简述） | 见下文 | — | — | — | — | — | — | — |

## 逐个说明

### 1. harrydaihaolin/agent-readiness + agent-readiness-rules（最相关）
- 【原文】README：引擎是 Python CLI + Claude Code 插件 + MCP server；`scan . --json / --fail-below 70 / --only feedback / --baseline prev.json / --sarif / --report / --badge`；`--run` 在 Docker 里真跑测试；`apply-top-action`；`explain <rule>`；`init` 写 `.agent-readiness.toml`；`list-checks`。设计原则明写"agent 是 headless 的""扫描器本身也全 headless：稳定 JSON、有意义的退出码"。
- 【原文】规则包 README：纯数据、无 Python；目录 `rules/{cognitive_load,feedback,flow,safety,ontology}/*.yaml`；`manifest.toml` 含 `rules_version`（YAML schema 版本）、`protocol_compat`、`pack_version`（semver：加规则升 minor，删/改名升 major）；加载器**拒绝不认识的规则**；CI 用 JSON Schema 校验 + 在 `agent-readiness-fixtures` 夹具仓库上跑参考评估器并比对快照。
- 【原文】条款文件样例（`rules/feedback/test_command.discoverable.yaml`）：字段 `rules_version / id / provenance / pillar / confidence / title / weight / severity / explanation / match / fix_hint / fix_template / verify / fix_prompt`。`match` 是声明式匹配器：`type: composite`（`op: or` + `clauses`）、`command_in_makefile`、`regex_in_files`（带 `file_globs`）、`path_glob`、`regex_secret_scan` 等；`fire_when: missing`。`verify.command` 给出修复后复检命令。
- 【原文】技术栈处理：同一条规则里把多语言信号并成 glob/regex 并集（`*_test.go`、`Cargo.toml`、`pyproject.toml [tool.pytest]`、`package.json "test"` 等），不分前端/后端；规则里没有 per-language 条件字段（我只读了 2 个样例规则，**其余规则是否有语言字段【未核实】**）。
- 【原文】许可/治理：规则 MIT，但 `TRADEMARK.md` 保留品牌名；`LICENSE-NOTICES.md` 规定重分发单条规则的署名。README 提到一个"closed insights engine"会在部署时 pip 安装规则包——**商业闭源层叠在开源规则之上**。
- 【推断】成熟度偏低（星 10 / 1），但架构（规则包 + 协议 schema + 夹具仓库 + 版本握手）是调研里最完整的。引擎仓库在 GitHub API 中许可证为 null，使用前需自行确认。

### 2. ambient-code/agentready（成熟度最高的同类）
- 【原文】README：评估 git 仓库，输出总分与 Platinum/Gold/Silver/Bronze；HTML + Markdown 报告；schema 版本化 + 校验/迁移工具；容器、`pip install agentready`、`uvx` 均可；`agentready assess <repo> --config my-config.yaml`；示例输出含 "23/25 (2 skipped)" 与 "Languages detected"。
- 【原文】Tier 分层：Tier1 Essential 55% / Tier2 Critical 27% / Tier3 Important 14% / Tier4 Advanced 4%；"缺 test execution 的影响是缺高级特性的 10 倍"。权重文件 `default-weights.yaml` 注明依据（Anthropic、Red Hat、ETH Zurich 等），并有 ADR 式变更记录（删除 repomix_config、code_smells 等冗余项）。
- 【原文】`BaseAssessor`：每个属性一个类，必须实现 `attribute_id`、`tier`、`assess()`；`assess()` **不得抛异常**，返回 `Finding`（状态含 pass/fail/skipped/error/not_applicable、score、evidence、remediation）；`is_applicable(repository)` 默认 True，子类可按语言/是否有 OpenAPI 等返回 False。语言通过根目录 manifest 文件映射检测（go.mod→Go、package.json→JavaScript、Cargo.toml→Rust…）。
- 【原文】用户配置 `.agentready-config.yaml`：`weights` 必须和为 1.0。有 `align` 命令做自动修复（`--dry-run` 预览），`FixerService`。
- 【推断】尺子（属性定义、阈值）散在 Python 代码里，只有权重可外部配置，换尺子要改代码。LLM 使用、退出码语义我没核实。

### 3. 0xmariowu/AgentLint
- 【原文】README：51 条确定性检查/6 维度（Findability、Instructions、Workability、Safety、Continuity、Harness）+ 7 条 opt-in 扩展（Deep/Session，用 AI 子 agent 和本地 Claude Code 会话日志）；`agentlint check`；Claude Code 里 `/al` 走"扫描→选修复项→自动修→重评分→存 HTML 报告"；修复项分 `guided` / `assisted`；证据在 `standards/evidence.json`。检查项带 ID（I5、W4、S3、H3…）和"为什么"一句话。
- 【推断】"核心确定性 + 可选 AI 扩展"的分层与我们的三段式相近；检查项带 ID + 理由 + 证据引用，可借鉴。

### 4. paladini/harness-score（星数最高）
- 【原文】`npx harness-score`；L0–L4 成熟度，等级按"harness 形状"设门槛（80 分文档但零测试也上不去）；108 分/6 维度/36 项；零 LLM、零网络、可复现；`--json` 的 JSON 形状、CLI 标志与退出码（0 通过 / 1 门禁失败 / 2 用法错误或扫描不完整）被写进稳定性承诺：改检查项只在 minor 版本发，且"改变的是仓库得分而非契约"。
- 【推断】它度量的是"AI 工具配置（rules/skills/hooks）成熟度"，偏 harness 而非仓库代码本身；"退出码 2 = 扫描不完整"的设计值得学。

### 5. tittle-xyz/toaster-ready
- 【原文】Go CLI；11 个加权类别 0–100；确定性、"评分路径无 LLM"；判断题/链接解析/持久化放"可选 skill 层"，二进制保持纯；`toaster gate . --min 50`；`.toaster-ready.yml` 可改 `weights`、`disabled`、`languages`（检测失败时提示技术栈）、`contextBudget`、`gate.threshold`；**未知类别 id 直接拒绝（类别集合固定以保证可比）**。
- 【原文】三态信号：`ok` / `no-data`（含原因）/ `not-applicable`；no-data 绝不记 0，报告 `dataComplete:false` 并说明卡在哪；N/A 从评分中剔除并重分配权重。示例：403 读分支保护没有 admin token = no-data 而非 0。
- 【推断】这是三段式 + N/A 语义设计最干净的一个，最该读完整 ADR（仓库有 `docs/adr/`，我没读）。

### 6. exadel-inc/agentic-readiness-assessment
- 【原文】Claude Code / Codex / Cursor / Junie 等多宿主插件（三份 manifest：根 `plugin.json`、`.codex-plugin/`、`.claude-plugin/`，`version` 以根文件为准并同步）；14 区域加权满分 105，**不适用的区域按 archetype 标 N/A 并从最大分扣除**；3 个 gate 锚定在 setup / deliverable / 该 archetype 的主验证面，"高均分不能掩盖 gate 失败"；Guardrails 有硬上限（权限绕过、blanket allow-all、未保护的密钥文件、已提交明文凭据 → 第 13 区域封顶 2 分，且各自成 P0/P1 修复项；只报路径不报值）；"没执行的命令只是声明"，要求记录命令/工作目录/结果；做一次可逆探针编辑验证"改→绿"后还原；状态 Ready/Partially/Not ready + 验证置信度 High/Medium/Low；报告带 `prompt_version`，同 MAJOR.MINOR 可比，minor 可能改分，major 不可比。
- 【原文】只写一个文件 `reports/agentic-readiness.md`，13 个固定章节。
- 【推断】全 LLM 执行，无 JSON/退出码，难 CI 化；但 gate / 硬上限 / 置信度 / 版本可比性声明 / 探针编辑的设计很值得借。

### 7. superduck-ai/agent-readiness
- 【原文】Factory 流程的开源复刻：82 条/9 类；5 阶段 skill，Phase 3 由并行 subagent 读 `criteria/*.md`；条款是一行 markdown：`**unit_tests_exist** (Level 1, App): 说明…`，带 Level（1–4）、scope（App/Repo）、`[Skippable]`；结果状态 passed/failed/skipped/missing，分数 `numerator/denominator`（App 级条款按"通过的应用数/总应用数"）+ 必填 rationale；产物 `.agent-readiness/history/*.json`（建议提交）和 `latest/`（忽略）。条款里直接按技术栈写分支（"JS/TS: … Python: …"）。
- 【推断】尺子（md）与引擎（打包的 mjs）有物理分离，但条款是自然语言，判定非确定性；"App 级 vs 仓库级 scope"对 monorepo 有启发。

### 8. goshipit（Capta1nRaj）
- 【原文】Agent Skill，210 检查/15 类，可在 `goshipit.md` 里取消勾选，sub-agent 只拿到勾选项；README 自带 "Token hungry" 警告；报告 `prelaunch-report.md`。偏上线前审计（含 SEO/计费/法务），与"agent 就绪度"重叠有限。

### 9. 其他一句带过
- markmishaev76/ai-harness-scorecard：5 类 32 条 A–F，侧重"agent 产出的代码是否可靠"（DORA/Harness Engineering 研究依据）；有 Action + badge。【原文】README。
- agentlint/agentlint（另一个同名项目）3★；EShener/agent-ready 1★；viktor-silakov/readiness 2★（8 支柱 1–5 级，Factory 启发）；ordinary9843/claude-code-auditor 0★（给 CLAUDE.md/SKILL.md 等 Claude Code 工件打 A–F，CI 脚本调 Anthropic API）：只在搜索摘要与 gh 元数据中看到，【未核实】内容。
- agentready-org/standard（ora.ai + Vercel）：是"网站/产品对 agent 可用"的标准，含 `spec/practices.json` 机器可读要求清单，**不是代码仓库评估**，不相关，但"规范 md + 机器可读 json 并存、稳定 `AR-*` 编号、退役编号记入 CHANGELOG"可参考。【原文】README。
- modiqo/cliare（CLI 的 agent 可用性）、nextdev-labs/mcp（API 可用性）、aws-samples/sample-agentic-readiness-analysis-orchestrator（服务组合是否适合 agent 化）、GetCassis/dbt-agent-readiness、forter/agentic-readiness-guide（指南文档）：均不是代码仓库维护就绪度，仅从 gh 描述判断，【未核实】。
- 若干 `agents-md-lint` 类小项目（0★）：只检查 AGENTS.md/CLAUDE.md 内容与路径是否虚构，属单点工具。

## 可借鉴

1. **尺子独立成包**（harrydaihaolin）：`manifest.toml`(rules_version / protocol_compat / pack_version) + JSON Schema 校验 + 夹具仓库快照测试；加载器拒绝不认识的规则；加规则 minor、删/改名 major。
2. **条款字段**：id、provenance、title、weight、severity、confidence、explanation（为什么）、match（声明式）、fix_hint / fix_template、verify.command（修复后如何复检）、fix_prompt（给 agent 的一段话）。我们的"必须/建议、档位、豁免"可直接作为同级字段补充。
3. **三态信号 + N/A**（toaster-ready）：ok / no-data / not-applicable；no-data 不记 0，说明卡在哪（我们的"判断题 agent 没裁决"可映射为 no-data）；N/A 从分母剔除；类别/条款集合固定以保可比，只开放权重、禁用、阈值。
4. **gate + 硬上限 + 置信度**（Exadel）：高均分不能掩盖关键项失败；安全类（明文凭据、allow-all）封顶；评分置信度与分数并报；报告带规则版本，声明跨版本可比性。
5. **退出码语义**（harness-score）：0 通过 / 1 门禁失败 / 2 扫描不完整；JSON 形状只增不删，写进稳定性承诺。
6. **`assess()` 不得抛异常，返回带状态的 Finding**（ambient-code）：错误也是一种结果，不让一个条款拖垮整次扫描。
7. **历史快照**（superduck）：`history/*.json` 提交入库、`latest/` 忽略，天然支持"复检对比"。
8. **`--baseline prev.json`**（harrydaihaolin）：复检对比有现成命令形态。
9. **条款带"为什么"与证据来源**（AgentLint 的 evidence.json、ambient 的 research report/ADR）：权重有据可查，也方便裁决争议。
10. **多宿主 manifest 同步**（Exadel）：根 `plugin.json` 为准，`.claude-plugin/`、`.codex-plugin/` 由脚本同步（它有 `sync_versions.py`），可直接对应我们要发 Claude Code + Codex 插件的需求。

## 坑

1. **分数不可比、权重主观**：各家权重来源多为作者判断或二手研究，ambient 自己也在迭代删/移条款；我们要把"权重/档位由谁定、依据是什么"写进条款文件。
2. **"确定性"名不副实**：纯 LLM 型（Exadel、superduck、goshipit）同仓库两次结果可能不同，且烧 token（goshipit 自己警告）；我们的"agent 只裁决判断题"要把判断题范围限死并缓存裁决结果。
3. **只检查"有没有 AGENTS.md"会被刷分**：toaster-ready 特意检查"是否与代码一致、命令引用是否断链、是否超上下文预算"；单点 lint 工具很多，容易重复造轮子。
4. **技术栈区分都很浅**：目前是并集 glob 或条款内多语言分支，对前端/后端、monorepo 没有成熟方案；如果我们做"按技术栈条款包"，是差异化点，但也没有现成可抄的格式。（【推断】）
5. **规则与引擎分仓的运维成本**：harrydaihaolin 需要 protocol 包 + 规则包 + 夹具包 + 引擎包四个仓库联动，星数仅个位数；过早拆分有负担。
6. **许可与商业化混杂**：该项目规则 MIT 但保留商标，且有闭源引擎层；引擎仓库许可证字段为空，不能直接复用其代码。
7. **成熟度普遍偏低**：除 harness-score（632★）、ambient-code（157★）外大多 <70★，规则质量与持续维护都不保证；Claude Code 插件市场里同类条目多为 0–3★ 的个人项目（来自 WebSearch 摘要，【未核实】）。
8. **"harness 评分"和"仓库适合 agent 维护"是两回事**：harness-score / AgentLint 评的是 AGENTS.md、hooks、rules 等配置成熟度，对"能否自动提 PR / 自动合并"（测试、CI、分支保护、回滚能力）覆盖较弱；我们的目标更接近 ambient-code + Exadel 的口径。（【推断】）

## 来源（均于 2026-11-19 通过 gh api / WebSearch 读取）

- https://github.com/harrydaihaolin/agent-readiness （README、docs/RUBRIC.md 摘要）
- https://github.com/harrydaihaolin/agent-readiness-rules （README、manifest 说明、`rules/feedback/test_command.discoverable.yaml`、`rules/flow/makefile.help_target.yaml`、`rules/safety/secrets.basic_scan.yaml`、文件树）
- https://github.com/ambient-code/agentready （README、`.agentready-config.example.yaml`、`src/agentready/data/default-weights.yaml`、`src/agentready/assessors/base.py`、`src/agentready/cli/align.py`）
- https://github.com/0xmariowu/AgentLint （README）
- https://github.com/paladini/harness-score （README）
- https://github.com/tittle-xyz/toaster-ready （README）
- https://github.com/exadel-inc/agentic-readiness-assessment （README、文件树）
- https://github.com/superduck-ai/agent-readiness （README、`agent-readiness/criteria/testing.md`）
- https://github.com/Capta1nRaj/goshipit （README）
- https://github.com/markmishaev76/ai-harness-scorecard （README）
- https://github.com/agentready-org/standard （README）
- 仅元数据/搜索摘要（【未核实】内容）：agentlint/agentlint、EShener/agent-ready、viktor-silakov/readiness、ordinary9843/claude-code-auditor、modiqo/cliare、nextdev-labs/mcp、aws-samples/sample-agentic-readiness-analysis-orchestrator、GetCassis/dbt-agent-readiness、forter/agentic-readiness-guide；WebSearch 结果聚合页（awesome.ecosyste.ms、claudepluginhub.com、pypi.org 等）。
