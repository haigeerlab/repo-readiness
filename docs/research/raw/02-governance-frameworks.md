# 02 通用仓库治理 / 评分卡框架调研

调研日期 2026-11-19。只读调研，未安装或运行任何被调研工具。标注含义：【原文】= 来自所附 URL / 仓库文件；【未核实】= 没找到原文佐证；【推断】= 我的归纳。星数、许可证、归档状态来自 `gh api repos/...` 当日读数。

## 结论先说

1. **没有一个现成框架同时满足"尺子是输入 + 必须/建议分档 + 门槛累进 + N/A + 带到期豁免 + 按应用判"**。最接近的是三类的拼合：
   - 条款形态（MUST/SHOULD/SUGGESTED、N/A 需理由、分级）→ OpenSSF Best Practices Badge 的 `criteria.yml`。
   - 逐档累进、"本档必须全过才进下一档"→ Port / OpsLevel / Backstage Maturity / Soundcheck 这类评分卡。
   - 带到期日的豁免（状态机 PENDING/APPROVED/REJECTED/REVOKED/EXPIRED）→ Cortex。
   - 没有任何一个同时有"建议项 ≥80%"这种百分比门槛；这是我们要自己定义的部分。【推断】
2. **规则与引擎分离的程度**：repolinter、Scorecard 的 policy/annotations、safe-settings、Allstar、Backstage Tech Insights、Cortex/Port 都是"规则是数据文件、引擎是通用的"。Scorecard 的 checks 本身是写死在 Go 里的，只有"阈值 policy"和"注解"是外置数据；最核心的"检查逻辑"不能靠改文件增减。
3. **可直接复用的引擎很少**：
   - repolinter 规则格式最贴近我们（条款=JSON/YAML、`where` 条件套用、`fix`、`extends`），但**已归档**（2026-02-06），最后一个 release v0.12.0（2025-05-09）。不建议依赖，只借格式设计。
   - Scorecard 是活跃的（v5.7.0，2026-11-19 发布），其"probe（原子探针）"层和 OSPS Baseline conformance 模式（实验性）可以当**确定性扫描的证据源**，但不能当我们的评分引擎。
4. **推荐路线**【推断】：自己写一个很薄的"条款加载 + 门槛打分"引擎；确定性扫描的 GitHub 设置类证据（分支保护 / rulesets、Workflow 权限、固定依赖）尽量复用 Scorecard 的 probe 输出（JSON）做输入，而不是重写判据。

## 对比表

| 框架 | 状态 / 许可证（当日读数） | 规则与引擎分离 | 规则格式 | 分级与门槛 | N/A / 豁免 | 条件化 / 分层 | 修复 | 复检 / 趋势 |
|---|---|---|---|---|---|---|---|---|
| OpenSSF Scorecard | 活跃，Apache-2.0，v5.7.0 | 部分：check 写在 Go 里；外置的只有 policy、annotations、probe 的 def.yml 元数据 | 每个 probe 一个 `def.yml`（id/lifecycle/motivation/outcome/remediation/ecosystem）；annotations 用 `scorecard.yml` | 每项 0–10 分；总分按风险加权平均（Critical 10 / High 7.5 / Medium 5 / Low 2.5）；Branch-Protection 内部有分档累进 | annotations 有 `not-applicable` / `test-data` / `remediated` 等理由；**不改分数，只做展示**【推断】 | 每个 check 声明支持的 repo 类型（GitHub/GitLab/local…）；conformance 模式有 `--profile` | 只给 remediation 文本；不自动修 | scorecard-action 定期跑；API 只查最新结果【未核实有历史趋势】 |
| OpenSSF Best Practices Badge | 活跃，MIT | 是：`criteria/criteria.yml` 与 Rails 应用分离 | 见下 | passing / silver / gold；MUST 全满足，SHOULD 满足或写理由，SUGGESTED 只需"考虑过" | `na_allowed`、`na_justification_required` 等字段，N/A 要写理由；无到期日 | 同一 YAML 按 level 分组；另有 baseline 1/2/3 的独立 yml | 无（自评+部分自动填） | 徽章定期需续；无趋势 |
| repolinter | **已归档**，Apache-2.0 | 是 | JSON/YAML ruleset：rules → {level, rule{type,options}, where, fix, policyInfo} | 只有 error/warning/off；无分档、无百分比 | 无豁免机制；`level: off` 关闭 | `where` + axioms（按语言/许可证/贡献者数）；`extends` 引用另一份 ruleset | `fix` 有 file-create/modify/remove，默认自动执行，`--dryRun` 关闭 | 无 |
| Backstage Tech Insights (+Maturity) | 活跃，Apache-2.0 | 是：check 写 `app-config.yaml`，引擎 json-rules-engine | `factIds` + `rule.conditions.all/any` | Maturity 插件：Stone / Bronze / Silver / Gold，逐档要求下面所有档的 check 全过 | 无内置豁免【未核实】 | 事实检索器按实体；Maturity 只对 kind: Component 的 check 页面【原文】 | 无 | facts 存历史，`lifecycle` 控制保留 TTL / maxItems |
| Spotify Soundcheck | 商业插件（Spotify 的 Backstage 付费插件）【推断】 | 是：Track / Level / Check 都是配置 | Track（含 levels）可导出 YAML，checks 需另导 | Track 由 Level 构成，通过一个 Level = 一张 Certification | 未查到 | Track 可限定实体 | 无 | 有认证结果 API【原文】 |
| Cortex | 商业 SaaS | 是（scorecard as code） | YAML：name/tag/description/draft/exemptions/ladder.levels/rules[title,expression(CQL),identifier,weight,level,filter]/filter/evaluation.window | Level（Bronze/Silver/Gold，逐档累进）或 积分制，二者可并用 | **临时豁免有到期日**，状态含 EXPIRED；过期后规则恢复正常评估 | scorecard 级 + rule 级 filter（实体类型、group、CQL） | 无 | 默认每 4 小时评估；有 Initiatives（带截止日期的推进活动） |
| OpsLevel | 商业 SaaS | 是（Terraform / API / opslevel.yml） | rubric = category（行）× level（列）；check 绑定一个 category 和一个 level | 过完本级全部 check 进下一级；兜底级 Beginner | 本次未核实（文档索引里没有豁免页） | Filter（谓词，可嵌套一层，如"Python 服务 + Tier1"）挂到 check 上 | Campaigns（带提醒的推进活动） | 未核实 |
| Port | 商业 SaaS | 是（JSON 定义） | JSON：identifier/title/blueprint/levels/filter/rules[identifier,title,level,query{combinator,conditions}] | 默认 Basic/Bronze/Silver/Gold；一个 scorecard 绑定一个 blueprint；必须通过本级及以下所有规则才到该级 | 本次未核实 | scorecard 级 filter（平铺，不允许嵌套）；不再匹配时 Port 删除该实体的结果 | 无 | 未核实 |
| Allstar | 活跃，Apache-2.0；**OpenSSF 托管 App 已下线**，现需自托管（Action 或 daemon） | 是：策略 JSON/YAML 在 `.allstar` 仓库 | 每个策略一个文件，字段如 `action`、`enforceDefault`、`approvalCount`、`optConfig` | 只有通过/不通过 | opt-in / opt-out + 仓库级覆盖 | 组织级默认 + 仓库级覆盖 | action：`log`、`issue`、`fix`、`email`；`fix` 因策略而异（如分支保护、secret scanning） | 通过 issue 生命周期 |
| github-community-projects/safe-settings | 活跃，ISC | 是 | `.github/settings.yml`（org）+ `suborgs/*.yml` + `repos/*.yml` | 无评分，只是"期望状态" | — | org → suborg → repo 三层合并；suborg 可按仓库名、team、custom property 分组 | **自动应用设置**，PR 里 dry-run 校验，定时同步防漂移 | 无评分 |
| legitify | 活跃，Apache-2.0 | 部分：策略是 OPA Rego，带 METADATA（title/severity/remediationSteps/threat） | `.rego` + 注释元数据 | 只有严重度分组 | 未核实 | 按 namespace（organization/repository/member 等）分 | 只给修复步骤 | 输出 JSON / SARIF |

## 逐个

### 1. OpenSSF Scorecard
- 状态：`ossf/scorecard` 未归档，Apache-2.0，最新 release v5.7.0（2026-11-19）。【原文】`gh api repos/ossf/scorecard`
- 检查与风险等级：docs/checks.md 列出 Binary-Artifacts(High)、Branch-Protection(High)、CI-Tests(Low)、CII-Best-Practices(Low)、Code-Review(High)、Contributors(Low)、Dangerous-Workflow(Critical)、Dependency-Update-Tool(High)、Fuzzing(Medium)、License(Low)、Maintained(High)、Packaging(Medium)、Pinned-Dependencies(Medium)、SAST(Medium)、SBOM(Medium)、Security-Policy(Medium)、Signed-Releases(High)、Token-Permissions(High)、Vulnerabilities(High)、Webhooks(Critical)。【原文】https://github.com/ossf/scorecard/blob/main/docs/checks.md
- 打分：每项 0–10，总分是按风险加权平均，权重 Critical 10 / High 7.5 / Medium 5 / Low 2.5。【原文】https://github.com/ossf/scorecard/blob/main/README.md
- 本地 / Actions：有 `--local` 标志（FlagLocal）；checks.yaml 里每个 check 标了支持的 repo 类型，很多只支持 GitHub，部分带 `local`。官方 `ossf/scorecard-action`（Apache-2.0，活跃）支持 `push`、`schedule`，输出 json/sarif/intoto，`publish_results: true` 才进公共 API 和徽章。【原文】https://github.com/ossf/scorecard-action
- rulesets 支持：Branch-Protection 说明"通过 GitHub 分支保护或 repository rules（rulesets）设置判定"，且所有设置都能通过 Repo Rules 读到；非管理员 token 读不到的项（DismissStaleReviews、EnforceAdmins、RequireLastPushApproval、RequiresStatusChecks、UpToDateBeforeMerge）在 rulesets 里可读；**只要任何一条规则有 bypass actor，EnforceAdmins 就算 false**。【原文】docs/checks.md
- Branch-Protection 是内置的**分档累进**：Tier1(3 分)禁强推/禁删分支；Tier2(6)至少 1 个审核人等；Tier3(8)至少 1 个状态检查；Tier4(9)至少 2 个审核人 + code owner；Tier5(10)失效旧审核 + 管理员也受约束。"低一档没全满足，高一档不给分"。【原文】docs/checks.md。这个思路和我们的"逐档累进"同构。
- Dangerous-Workflow（Critical）判据：①`pull_request_target` / `workflow_run` 触发且显式检出 PR 代码；②把 `github.event.issue.title` 之类不可信上下文直接拼进脚本。有声明"不检测不可信检出是否被安全使用（例如仅限带标签的 PR）"。【原文】
- Token-Permissions（High）：顶层 `permissions` 设为只读、写权限放到 job 级为满分；所有 job 都定义了权限但顶层没定义扣 1 分；对 `contents` / `packages` / `security-events` 等写权限给警告，识别到打包 / 上传 SARIF 动作则不扣分。**检测不到仓库设置里的"默认只读"开关**，因为没有 API。【原文】
- Pinned-Dependencies（Medium）：看 Dockerfile、shell 脚本、GitHub workflow；要求按哈希固定；Go 的完整语义化版本算已固定；GitHub Actions 的 tag 若对应已发布的 immutable release 也算已固定。【原文】
- 规则/引擎分离：
  - probe 层：每个 probe 一个目录，`def.yml`（id、lifecycle、short、motivation、implementation、outcome、remediation{onOutcome,effort,text}、ecosystem{languages,clients}）+ `impl.go`。**元数据外置，逻辑仍在 Go**。【原文】probes/blocksDeleteOnBranches/def.yml
  - 阈值 policy：`policy/` 里解析 `policies: {<check>: {mode: enforced|disabled, score: N}}` + `version: 1`。【原文】policy/policy.go 的结构体
  - 注解 annotations：`scorecard.yml`（或 `.scorecard.yml`、`.github/scorecard.yml`），`annotations: [{checks:[...], reasons:[{reason: test-data|remediated|not-applicable|not-supported|not-detected}]}]`，需 `--show-annotations` 才显示。【原文】config/README.md
  - conformance 模式（**实验性**）：`--catalog=osps-baseline --profile=maturity-1 --format=json|gemara`。结果集 PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NEEDS_REVIEW；目前只评估 OSPS-AC-03.01、AC-03.02 两条，其余列入 `notEvaluated`；**不支持 `--local`**。文档明说"启发式信号，不是认证"。【原文】docs/conformance.md
- 对我们：Scorecard 的结果枚举（含 UNKNOWN 与 NEEDS_REVIEW）、`notEvaluated` 的显式列出、`evidence[]` 里挂探针原始发现，这三点都值得照抄。

### 2. OpenSSF Best Practices Badge
- 状态：`ossf/best-practices-badge`，MIT，活跃。【原文】gh api
- 分级：`criteria.yml` 顶层 key `'0'` / `'1'` / `'2'`，对应 passing / silver / gold（行号 39 / 704 / 1321）；我数到 MUST 109 条、SHOULD 22 条、SUGGESTED 15 条（对 `category:` 行计数，三个 level 合计，**可能含已废弃项**）【推断】。
- 门槛规则（原文）："所有 MUST / MUST NOT 必须满足；所有 SHOULD 要么满足、要么写明不实施的理由；所有 SUGGESTED 只需被'考虑'（标记为满足或不满足）。"【原文】https://github.com/ossf/best-practices-badge/blob/main/docs/criteria.md
- 每条条款的字段：`category`(MUST|SHOULD|SUGGESTED)、`future`、`obsolete`、`na_allowed`、`na_justification_required`、`met_justification_required`、`met_url_required`、`description`、`details`、`rationale`、`autofill`（自动填写思路）等。【原文】criteria/criteria.yml 头部注释
- N/A：只有 `na_allowed` 的条款能选，选了常要写理由。没有到期日。【原文】
- 自评 + 自动检测：对遵循标准惯例、托管在 API 友好站点（如 GitHub）的项目自动检测并预填；`autofill` 字段只是想法，"不保证实现"。【原文】
- 另有 `baseline_criteria.yml`（来自 OSPS Baseline，64 条，结构同上并带 `original_id`、`na_allowed`），以及 `baseline_to_metal_map.yml` / `metal_to_baseline_map.yml` 两个映射。【原文】
- 对我们：字段设计（category / na_allowed / na_justification_required / met_url_required / future / obsolete / autofill / rationale）是最成熟的一份"条款 schema"，几乎可以直接当字段表。注意它的"建议"门槛是"考虑过即可"，不是百分比。

### 3. TODO Group repolinter
- **已归档**：`archived: true`，最后 push 2026-02-06；README 首段即写明 "has been archived"；最新 release v0.12.0（2025-05-09）。Apache-2.0。【原文】`gh api repos/todogroup/repolinter` 与 README
- 规则文件：JSON 或 YAML ruleset，`version: 2`，`$schema` 指向 rulesets/schema.json；`axioms` 映射（如 `linguist: language`、`licensee: license`、`packagers: packager`）；`rules.<name>: {level: error|warning|off, rule:{type, options}, where:[...], fix:{type, options}, policyInfo, policyUrl}`。【原文】README 与 rulesets/default.json
- axioms：`contributor-count`、`licensee`、`linguist`、`packagers`；`where` 语法 `<axiom>=<value>`，数值型 axiom 可比较（`contributors>6`）；所有 `where` 都满足才跑。【原文】docs/axioms.md、README
- rule 类型示例：`file-existence`、`file-contents`、`file-not-contents`、`file-no-broken-links`、`git-grep-commits`、`license-detectable-by-licensee`、`best-practices-badge-present`、`json-schema-passes` 等。【原文】docs/rules.md 标题
- `extends`：顶层写一个 URL 即可扩展另一份 ruleset。【原文】README
- fix：`file-create`、`file-modify`、`file-remove`；**默认自动执行**，`--dryRun` 关闭；`--git` 可直接克隆远程仓库。【原文】README、docs/fixes.md
- 没有分档、没有百分比、没有豁免、没有 N/A（除了 `level: off`）。
- 对我们：格式设计（规则=类型+选项、`where` 条件、`extends`、`policyInfo/policyUrl`）可借；引擎不要用（已归档，Node 12 时代依赖）。

### 4. 评分卡类
- **Backstage Tech Insights**（Apache-2.0，活跃）：`techInsights.factChecker.checks.<id>` 含 `type: json-rules-engine`、`name`、`description`、`factIds`、`rule.conditions.all|any[{fact, operator, value}]`；FactRetriever 负责采集事实并按 `lifecycle` 保留历史（TTL 或 maxItems）。Maturity 插件加了 Stone/Bronze/Silver/Gold 排名：Bronze=过全部 Bronze check，Silver=过 Bronze+Silver，以此类推。【原文】community-plugins/workspaces/tech-insights 下各 README
- **Spotify Soundcheck**：Track 由 Level 构成，Level 由 Check 构成；通过一个 Level 得 Certification；Track 可导出 YAML 但 check 要另导。【原文】https://backstage.spotify.com/docs/plugins/soundcheck/core-concepts/tracks
- **Cortex**：
  - 定义：YAML 字段 name/tag/description/draft/exemptions/ladder.levels/rules[title, expression, identifier, weight, level, filter]/filter/evaluation.window。【原文】https://docs.cortex.io/standardize/scorecards/scorecards-as-code
  - 规则不能在多个 level 重复，类似规则可用不同阈值放不同 level；level 制和积分制可并用；默认每 4 小时评估。【原文】https://docs.cortex.io/standardize/scorecards/create
  - 豁免：永久或"若干天"的临时豁免，须写理由；状态 PENDING / APPROVED / REJECTED / REVOKED / EXPIRED；**过期后规则按正常评估**；豁免的规则在 level 制下"允许继续升级"，在积分制下"不计入平均"；被拒 / 撤销 / 过期的都按不通过算。【原文】https://docs.cortex.io/standardize/scorecards/rule-exemptions
- **OpsLevel**：rubric = category × level；默认 Bronze/Silver/Gold，可自定义；**过完本级全部 check 才进下一级**（文中未明说是否要求更低级全过）；有兜底级 Beginner（不能放 check）；filter 用谓词，可组合，只支持一层嵌套，例子是"Python 服务 + Tier 1"。【原文】https://docs.opslevel.com/docs/categories-and-levels.md 、https://docs.opslevel.com/docs/checks-and-filters.md
- **Port**：JSON 定义，一个 scorecard 绑定一个 blueprint；`levels` 默认 Basic/Bronze/Silver/Gold；`rules[].level`、`rules[].query.{combinator,conditions}`；实体必须按顺序通过每一级全部规则才升级，"只过了两条 Bronze 里的一条，Silver 全过也停在 Basic"；`filter` 平铺不允许嵌套。【原文】https://docs.port.io/promote-scorecards/
- 共同点：它们都把"逐档累进"当成默认语义，且都按"实体"（服务/组件）来评，这点与我们"monorepo 按应用判"天然对齐。

### 5. 其他同类
- **Allstar**（Apache-2.0，活跃）：README 开头声明"OpenSSF 托管 App 已下线，需自托管"（Action 或 daemon）。策略配置放在组织的 `.allstar` 仓库，有 opt-in / opt-out 两种启用策略；action 有 `log`（默认）、`issue`、`fix`、`email`；分支保护策略字段含 `enforceDefault`、`approvalCount`、`requireStatusChecks`、`enforceOnAdmins` 等，仓库级可覆盖组织级。【原文】https://github.com/ossf/allstar
- **safe-settings**（ISC，活跃；仓库现在属 github-community-projects）：org / suborg / repo 三层 YAML 合并；suborg 可按仓库名、team 或 custom property 分组；默认分支的设置才生效，其他分支的 PR 只跑 dry-run 校验；定时同步防漂移；org 级目前仅支持 rulesets。【原文】README
- **legitify**（Apache-2.0，最近 push 2026-08-31）：策略是 OPA Rego，注释里 `# METADATA` 带 title / description / custom.severity / remediationSteps / threat / requiredScopes；输出 human / JSON / SARIF；覆盖 GitHub 和 GitLab。【原文】README、policies/github/repository.rego
- **OSPS Baseline**（OpenSSF 的 baseline.openssf.org）：当前版本 v2026.08.28，只含 MUST，没有 SHOULD；按 maturity level 1/2/3 分组。【原文】https://baseline.openssf.org/
- **Gemara**（Apache-2.0，活跃）：CUE 写的 GRC 数据模型；OSPS Baseline 是它的 Layer 2（控制目录），评估日志是 Layer 5；Scorecard 的 conformance 能输出 `--format=gemara`。【原文】https://github.com/gemaraproj/gemara
- **Privateer**（revanite-io/pvtr-github-repo 有 OSPS Baseline 的 GitHub 仓库插件，Layer 5）：只在 Gemara README 里看到列举，**未核实其细节**。
- 没查到名为 "Repo Doctor" 且活跃的同类，**未核实**。

## 回答你的 5 个问题

1. **规则与引擎是否分离、格式长什么样**
   - 分离得最彻底：repolinter（已归档）、Backstage Tech Insights、Cortex、Port、safe-settings、Allstar。
   - 半分离：Scorecard（check 写死，probe 元数据 / policy / 注解外置）、legitify（Rego 带元数据）。
   - 最小结构（取各家交集）：`id` + 判定（类型/表达式/查询）+ 等级/档位 + 条件（where / filter）+ 说明（描述、失败信息、修复文本、策略 URL）。条款字段最全的是 Best Practices Badge 的 criteria.yml。
2. **分级与门槛、N/A、豁免**
   - 分级：Badge 是 passing/silver/gold + MUST/SHOULD/SUGGESTED；评分卡是 Bronze/Silver/Gold 且逐档累进（Port、OpsLevel、Backstage Maturity、Cortex）；Scorecard Branch-Protection 内部有同样的累进。
   - **没有"必须全过 + 建议 ≥80%"的现成规则**；最接近的是 Badge 的"SHOULD 要么满足要么写理由"，和 Cortex 的"积分制百分比"，两者没人合在一起。
   - N/A：Badge 用 `na_allowed` + 必填理由；Scorecard 用 annotations 的 `not-applicable`（只展示不改分）；Scorecard conformance 有 `NOT_APPLICABLE` 结果值。
   - 豁免 + 到期：只有 Cortex 有明确的到期状态机；其他都没有。**"到期后规则恢复正常评估"**是 Cortex 的语义，我们可以抄。
3. **条件化与分层**
   - repolinter：`where` + axioms（语言、许可证、贡献者数）+ `extends`。
   - safe-settings：org → suborg → repo 三层合并；suborg 可按 custom property 分组。
   - Port / Cortex / OpsLevel：scorecard 级或 rule 级 filter；Port 绑定 blueprint（实体类型）；OpsLevel 的 filter 可组合一层。
   - Allstar：组织默认 + 仓库覆盖。
   - Scorecard conformance：`--profile`（maturity-1/2/3）。
4. **修复与复检**
   - 自动修复：repolinter（`fix`，已归档）、Allstar（`fix`，限特定策略）、safe-settings（直接应用设置）。
   - 只给建议：Scorecard（remediation 文本，StepSecurity 在线工具用于固定 Actions 与限制 token 权限）、legitify（remediationSteps）、Badge。
   - 复检 / 趋势：Backstage Tech Insights 存历史 facts；Cortex 定时评估、有 Initiatives；Scorecard 定时跑，对外 API 只给最新。**没有哪一家把"复检对比"当成一等输出**【推断】——我们的"复检对比"算差异化。
5. **对我们（见下节）**

## 可借鉴

- **条款 schema**：直接参考 Badge 的字段（category、na_allowed、na_justification_required、met_url_required、future、obsolete、rationale、autofill），再加我们自己的：档位、作用范围（仓库/应用）、适用范围、判定方式（确定性 / agent 裁决）、fix hint。
- **结果枚举**：用 Scorecard conformance 那五个值（PASS / FAIL / UNKNOWN / NOT_APPLICABLE / NEEDS_REVIEW），其中 `UNKNOWN` 和 `NEEDS_REVIEW` 正好对应"扫描证据不足"和"需要 agent 裁决"。
- **`notEvaluated` 显式列出**：报告里写清哪些条款没评，避免"没测的被当成通过"。
- **证据挂载**：每条结果带 `evidence[]`（probe、message、outcome），便于 agent 裁决和复检对比。
- **`where` / filter 与 `extends`**：用 repolinter 的 `<axiom>=<value>` 思路表达"适用范围"；`extends` 做条款包的组合。
- **逐档累进**：Port 的"本档所有规则过了才进下一档"，Scorecard Branch-Protection 的"低档没满足高档不给分"，都是同一语义；我们在其上加"建议项 ≥80%"。
- **豁免到期**：抄 Cortex 的状态集（含 EXPIRED）和"过期后恢复正常评估"；加到期日必填。
- **Scorecard 的 annotations 理由枚举**（test-data / remediated / not-applicable / not-supported / not-detected）是很好的豁免理由分类；其中 `not-detected`、`not-supported` 可对应"工具没识别到，但项目实际满足"，用于对扫描误判申诉。
- **按实体评分**：Port / OpsLevel / Cortex 的"一个评分卡 × 多个实体、每个实体各自一个等级"对应我们的 monorepo 按应用判。
- **Gemara**：如果将来想对接 OpenSSF 生态，Scorecard 已能输出 Gemara Evaluation Log；我们的 JSON 报告字段可以参照其 Layer 5 做映射。【推断】

## 坑

1. **repolinter 已归档**，且其 `fix` 默认自动执行（需 `--dryRun` 才关），照搬时要把默认改成"只预览"。
2. **Scorecard 的检测规则不能靠配置文件增减**；用它的"分数"当门槛会把我们的"必须/建议"语义吃掉，因为它是 0–10 加权平均，一个 Critical 满分也能掩盖别处缺失。建议只取它的 probe 证据。
3. **Scorecard 的 conformance 模式是实验性的**，目前只评 2 条 OSPS 控制，且不支持 `--local`。不要依赖它的输出格式稳定。
4. **Scorecard 对管理员设置的可见性有限**：没有管理员 token 时 `DismissStaleReviews` 等读不到；任何 rulesets bypass actor 会让 EnforceAdmins 判 false；Token-Permissions 读不到仓库设置里的"默认只读"开关。我们的 GitHub 设置类条款要预设"权限不足 → UNKNOWN，不是 FAIL"。
5. **Scorecard 的 Dangerous-Workflow 不判断"不可信检出是否被安全使用"**，会有误报，需要豁免通道。
6. **Allstar 官方托管 App 已下线**；safe-settings 与 Allstar 都是"强制写入"型，我们是"检测 + 建议"，不要混用语义。
7. **Cortex / OpsLevel / Port / Soundcheck 是商业产品**，格式只能借鉴，不能复用。我这里没读到它们的许可条款，不要复制其文档原文。【未核实】
8. **没有现成"建议项百分比"门槛**：要自己定义分母是否扣除 N/A 与有效豁免项，以及"建议项为 0 条"时的行为（我们的建议：分母为 0 视为满足；【推断】）。
9. **豁免会让档位"虚高"**：Cortex 的做法是豁免的规则当作通过去升级；我们要决定是否在报告里单独标"含 N 条豁免"，否则复检对比会因豁免到期而"掉档"，需要把"掉档原因=豁免过期"单列。【推断】
10. 数字类条款（Badge 的 criteria 计数等）我只是对 yml 做了粗略计数，**未排除 obsolete / future**，别当成精确数字引用。

## 来源

- OpenSSF Scorecard：https://github.com/ossf/scorecard （README.md、docs/checks.md、docs/conformance.md、config/README.md、probes/*/def.yml、policy/policy.go、docs/checks/internal/checks.yaml）
- Scorecard Action：https://github.com/ossf/scorecard-action
- Best Practices Badge：https://github.com/ossf/best-practices-badge （criteria/criteria.yml、criteria/baseline_criteria.yml、docs/criteria.md）
- repolinter：https://github.com/todogroup/repolinter （README.md、docs/rules.md、docs/axioms.md、docs/fixes.md、rulesets/default.json）
- Backstage Tech Insights：https://github.com/backstage/community-plugins/tree/main/workspaces/tech-insights
- Spotify Soundcheck：https://backstage.spotify.com/docs/plugins/soundcheck/core-concepts/tracks
- Cortex：https://docs.cortex.io/standardize/scorecards/create 、https://docs.cortex.io/standardize/scorecards/scorecards-as-code 、https://docs.cortex.io/standardize/scorecards/rule-exemptions
- OpsLevel：https://docs.opslevel.com/docs/categories-and-levels.md 、https://docs.opslevel.com/docs/checks-and-filters.md
- Port：https://docs.port.io/promote-scorecards/
- Allstar：https://github.com/ossf/allstar
- safe-settings：https://github.com/github-community-projects/safe-settings
- legitify：https://github.com/Legit-Labs/legitify
- OSPS Baseline：https://baseline.openssf.org/ 、https://github.com/ossf/security-baseline
- Gemara：https://github.com/gemaraproj/gemara
