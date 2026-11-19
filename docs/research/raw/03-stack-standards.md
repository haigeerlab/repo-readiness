# 03 按技术栈的成文工程标准（调研，2026-11-19）

标注约定：【原文】= 本次抓取到的页面内容（附 URL）；【未核实】= 仅来自搜索摘要、第三方页面或无法抓取原文；【推断】= 我的归纳。
抓取限制：WebFetch 返回的是小模型对页面的摘要，不是逐字原文，所以【原文】指"页面确有此内容"，不是逐字引用。

## 1. 结论先说

1. **跨栈的成文标准几乎都不按语言分级，而按"项目性质 / 规模 / 成熟度"分级。** OSPS Baseline 按维护者数量与用户规模分 L1/L2/L3，SLSA 按构建平台强度分级，Scorecard 20 项检查基本语言无关，Google code review 标准明说语言无关。这与我们"只写结果"的路线一致。【原文】
2. **各栈公认的"必有"，抽象成结果后高度趋同**：有自动化测试并在合并前跑、依赖可复现（锁定）、依赖有清单、密钥不进仓库、变更能追溯与审查、发布可验证。差异只在"用什么工具达成"（`go.sum`、`gradle.lockfile`、`pylock.toml`、`package-lock.json`……）。【推断，依据见第 2、3 节】
3. **真正需要点名手段的，是各栈的"静态检查入口"**（Go 的 vet/staticcheck、Rust 的 clippy、Shell 的 ShellCheck、前端的 tsc/ESLint）。但这些点名也只能当"该栈的达成示例"，不宜当硬性要求：没有一份跨栈成文标准把它们列为必须。【推断】
4. **"做样子"风险最高的是覆盖率百分比。** Google 自己明说没有普适的理想数字，给出 60/75/90 的参考档，并警告目标会被当成打勾项，倾向在代码评审里讨论未覆盖行，且多数团队用"警告而非阻断"。【原文，见第 4 节】
5. **有现成的"通用基线 + 按栈补充"做法**：OSPS 的生态示例（package.json、go.mod 等只作示例）、Scorecard 里个别检查对 Go 的特例（Fuzzing、Pinned-Dependencies）、SLSA 把实现细节交给各生态自定。本质是"结果层通用，手段层给示例"。【原文】
6. **建议：坚持"只写结果"作为尺子的必须层；增加一个"按栈达成示例"的附录（非必须），再加一个很短的"建议层"。** 不要把具体工具写进必须条款。详见第 6 节。

## 2. 按栈的表

"结果可通用化"列：是 = 可以写成不点名工具的结果；否 = 只能点名手段才说得清。
"来源强度"：成文 = 官方/权威组织页面；社区 = 第三方博客等。

### 2.1 前端 / Web（TS/JS）

| 条目 | 成文出处 | 结果可通用化？ | 必须 / 建议 | 备注 |
|---|---|---|---|---|
| 类型检查 | Next.js 生产清单"Use TypeScript and the TypeScript plugin…catch errors early"【原文】https://nextjs.org/docs/app/guides/production-checklist | 是（"类型/静态检查可在 CI 失败"） | 必须（对已使用类型系统的仓库） | 清单是"建议"口吻，非强制 |
| Lint（含 a11y 规则） | 同上"Use the built-in eslint-plugin-jsx-a11y…"【原文】 | 是 | 建议 | |
| 构建能在 CI 通过 | 同上"run `next build`…catch any build errors"【原文】 | 是 | 必须 | |
| Core Web Vitals 阈值 | web.dev：LCP ≤2.5s、INP ≤200ms、CLS ≤0.1，取第 75 百分位真实用户数据；阈值不分移动/桌面【未核实，来自搜索摘要的转述】https://web.dev/articles/defining-core-web-vitals-thresholds | 部分：它是线上真实用户指标，不是合并前能确定性判定的 | 建议（可观测层，而非合并门槛） | Next.js 清单明说 Lighthouse 是"模拟测试，应与现场数据一起看"【原文】 |
| Lighthouse CI 性能预算 | Lighthouse CI 配置：`warn` 级失败不使 CI 失败，`error` 才会；`budgetsFile` 可设资源预算【原文】https://github.com/GoogleChrome/lighthouse-ci/blob/main/docs/configuration.md | 是（"性能预算超限会让检查失败"） | 建议（性能敏感产品才升必须） | 阈值依赖产品，不宜通用定值 |
| Bundle 体积分析 | Next.js 清单点名 `@next/bundle-analyzer`【原文】 | 是（"体积有预算或可观测"） | 建议 | |
| 单测 / E2E | 本次未找到前端官方"必须有 E2E"的成文条款；DORA 的"test automation"是通用能力【未核实】 | 是 | 单测检查入口必须；E2E 建议 | |
| 无障碍（WCAG/axe） | 仅 Next.js 清单提到 jsx-a11y lint；WCAG/axe 具体标准本次未核【未核实】 | 部分 | 建议 | |
| 依赖审计 | 本次未取到 npm 官方 `npm audit` 页面【未核实】；OSPS/Scorecard 有通用的"已知漏洞"检查【原文】 | 是 | 建议 → 对自动合并升必须 | |
| 锁文件 | Scorecard Pinned-Dependencies【原文】https://github.com/ossf/scorecard/blob/main/docs/checks.md | 是 | 必须 | |

### 2.2 后端 / 服务

| 条目 | 成文出处 | 结果可通用化？ | 必须 / 建议 | 备注 |
|---|---|---|---|---|
| 一份代码库、多环境部署 | 12-Factor I【原文】https://12factor.net/ | 是 | 建议 | |
| 依赖显式声明并隔离 | 12-Factor II【原文】 | 是 | 必须（对应"依赖锁定"） | |
| 配置放环境变量、不进代码 | 12-Factor III；OSPS-BR-07.01 禁止把密钥提交进版本库（L1）【原文】https://baseline.openssf.org/versions/2026-02-19 | 是 | 必须（密钥不入库） | "放环境变量"是手段，"密钥不入库"是结果 |
| 构建/发布/运行分离 | 12-Factor V【原文】 | 是 | 建议 | |
| 无状态进程、快速启动与优雅关闭 | 12-Factor VI、IX【原文】 | 是 | 建议 | |
| 开发与生产一致 | 12-Factor X【原文】 | 是（对应"一条命令起环境"） | 建议 | |
| 日志作为事件流 | 12-Factor XI【原文】 | 是 | 建议 | |
| 管理任务作为一次性进程 | 12-Factor XII【原文】 | 是（含数据库迁移） | 建议 | |
| PRR 关注面 | SRE 书：架构与依赖、埋点/指标/监控、应急响应、容量规划、变更管理、性能【原文】https://sre.google/sre-book/evolving-sre-engagement-model/ | 是 | 建议（面向"接手生产"，不是合并检查） | |
| 发布清单 | SRE 书 Launch Checklist 10 类，含：故障转移与回退、监控、自动化与变更控制（可重复构建、金丝雀、分阶段推出）、外部依赖与优雅降级【原文】https://sre.google/sre-book/launch-checklist/ | 是 | 回滚路径必须；金丝雀/分阶段建议 | |
| 健康检查、API 契约（OpenAPI）、数据库迁移 | 本次未取到成文清单原文【未核实】 | 是 | 建议 | |

### 2.3 各语言社区（每语言 3–6 条）

本次只有部分语言取到官方页面。未取到的标【未核实】，仅供作为候选。

| 语言 | 条目 | 出处 | 结果可通用化？ | 必须 / 建议 |
|---|---|---|---|---|
| Python | `pyproject.toml` 作为项目元数据入口 | PyPA 指南存在"Writing your pyproject.toml"页【未核实：只见搜索结果，未读正文】https://packaging.python.org/guides/writing-pyproject-toml/ | 是（"依赖与构建配置有标准声明文件"） | 建议 |
| Python | 锁文件标准 `pylock.toml`（PEP 751）| 规范页存在；各工具支持程度不一，pip/uv/PDM/Poetry 状态来自第三方 2026-04 前后文章【未核实】https://packaging.python.org/specifications/pylock-toml/ | 是 | 必须"有锁定"，格式不限定 |
| Python | 类型检查、ruff 格式/lint | 本次未取到官方成文依据【未核实】 | 是 | 建议 |
| Python | PyPA 指南明说"不对许多任务做统一推荐，常列选项" | 【未核实：搜索摘要】https://packaging.python.org/en/latest/guides/tool-recommendations/ | — | 佐证"不点名工具"路线 |
| Go | `go.mod` + `go.sum` 提交进仓库，工具据此校验下载内容完整性 | 【原文】https://go.dev/doc/modules/managing-dependencies | 是 | 必须（等价于"依赖锁定"） |
| Go | `go mod tidy` 使 go.mod 与实际 import 一致 | 同上【原文】 | 是 | 建议 |
| Go | `go vet` 随工具链提供、`go test` 时自动运行；staticcheck/golangci-lint 为社区常用 | 来自第三方博客与技能页，无 go.dev 官方依据【未核实】 | 是 | 静态检查入口：必须；具体工具：建议 |
| Rust | Clippy 在 CI 中让警告失败：新版用 `build.warnings = "deny"`，旧版 `-Dwarnings`（官方说旧法会使构建缓存失效）| 【原文】https://doc.rust-lang.org/clippy/usage.html | 是 | 建议 |
| Rust | Clippy 默认组 `clippy::all` 开启；`pedantic`/`restriction` 默认关闭，官方提醒 restriction 不宜整组启用 | 同上【原文】 | — | 说明"全开"并非标准做法 |
| Rust | API Guidelines 清单 11 大类；"Necessities"仅两条（稳定 crate 的公开依赖也须稳定；宽松许可证）| 【原文】https://rust-lang.github.io/api-guidelines/checklist.html | 否（面向库作者，不适合通用门槛） | 仅库发布场景建议 |
| Java/Kotlin | Gradle 依赖锁定：`gradle.lockfile` 应纳入版本库；默认模式下解析结果与锁不一致则构建失败 | 【原文】https://docs.gradle.org/current/userguide/dependency_locking.html | 是 | 必须"有锁定"，Gradle 是达成示例 |
| Java/Kotlin | Maven 对应机制、静态分析（Checkstyle/SpotBugs 等） | 本次未核【未核实】 | 是 | 建议 |
| Shell | ShellCheck 是 shell 脚本静态分析工具；官方 wiki 目录列有 GitHub Actions、GitLab CI 等集成页，但正文本次未读到 | 【原文：工具定位】【未核实：集成建议】https://github.com/koalaman/shellcheck/wiki/Home | 是 | 对含大量 shell 的仓库建议 |

### 2.4 跨栈（是否按语言区分）

| 标准 | 是否按语言分 | 与尺子相关的条款 | 出处 |
|---|---|---|---|
| OSPS Baseline（页面标注版本 2026.02.19，共 64 条，L1 24 / L2 19 / L3 21，8 类）| 否，按项目性质与规模分级；package.json、go.mod 等只是示例 | QA-02.01 依赖清单（L1）；QA-03.01 合并前状态检查须通过或经人工明确豁免（L2）；QA-06.01 提交被接受前 CI 至少跑一个自动化测试套件（L2）；QA-06.02 文档说明测试何时如何运行（L3）；QA-06.03 重大变更应加/更新自动化测试的政策（L3）；QA-07.01 非作者的人工合并审批（L3）；BR-05.01 用生态标准的依赖管理工具（L2）；BR-07.01 密钥不入库（L1）；QA-05.01/.02 版本库不得含生成的可执行文件或不可审查的二进制（L1）| 【原文】https://baseline.openssf.org/versions/2026-02-19 （页面"当前版本"链接指向 2026-08-28，页面内容与版本对应关系不完全清楚）|
| OpenSSF Scorecard（20 项检查）| 否；仅 Fuzzing（当前只原生支持 Go fuzzing，另认若干语言的属性测试库）与 Pinned-Dependencies（Go 模块版本号视为已固定）有语言特例 | CI-Tests、Code-Review、Branch-Protection、Pinned-Dependencies、Dependency-Update-Tool、Vulnerabilities、Token-Permissions、SAST、SBOM | 【原文】https://github.com/ossf/scorecard/blob/main/docs/checks.md |
| SLSA | 否；实现（溯源格式、可复现构建等）交给各生态/组织。注意：我抓到的是 v1.0 页面，已标"Retired"，现行为 v1.2；v1.0 只有 Build 轨道（L1 有溯源、L2 托管构建+签名、L3 强化构建），无 Source 轨道 | 构建溯源 | 【原文】https://slsa.dev/spec/v1.0/levels （v1.2 内容未核实）|
| Google Engineering Practices（code review）| 否，标准语言无关；风格一律以风格指南为准。核心："CL 提升整体代码健康度即可批准，不求完美" | 人工审查的判据 | 【原文】https://google.github.io/eng-practices/review/reviewer/standard.html |
| DORA 技术能力 | 否；研究只度量实践是否存在，不度量具体工具。能力含持续集成、测试自动化、主干开发、部署自动化 | 通用能力清单 | 【未核实：搜索摘要】https://docs.cloud.google.com/architecture/devops |

## 3. 回答问题 1：哪些是结果、哪些只能点名手段

结果层（可通用化，各栈趋同）【推断，综合第 2 节】：

- 合并前有自动化检查，且能失败（OSPS QA-03.01、QA-06.01，Scorecard CI-Tests）
- 依赖可复现 + 有依赖清单（Go go.sum、Gradle lockfile、pylock.toml、12-Factor II、OSPS QA-02.01、Scorecard Pinned-Dependencies）
- 密钥不入库（OSPS BR-07.01、12-Factor III）
- 构建/发布与运行分离、可回退（12-Factor V、SRE Launch Checklist）
- 变更有人/有机制审查（OSPS QA-07.01、Scorecard Code-Review、Google Engineering Practices）
- 环境一致、一条命令可起（12-Factor X）
- 测试怎么跑有文档（OSPS QA-06.02）

只能点名手段才说清的【推断】：

- 前端的 Core Web Vitals 数值、Lighthouse 预算、axe/WCAG 级别：数值与工具紧耦合，且需要真实用户数据。
- 各栈的静态检查工具名（tsc、ESLint、vet、staticcheck、clippy、ShellCheck）：目的通用（"静态检查在 CI 失败"），工具名不通用。
- 锁文件格式：必须点名文件才能验证，但可以写成"达成示例"。

## 4. 回答问题 2：做样子风险高的条款与社区反思

| 条款 | 风险 | 社区/大厂的反思 |
|---|---|---|
| 覆盖率百分比 | 高：容易靠无断言测试凑数 | Google 测试博客：没有适用所有产品的理想数字，给 60%/75%/90% 作"可接受/值得称赞/示范"参考；警告目标会被当成打勾项；多数团队用只警告不阻断的工具；更推荐变异测试【原文：摘要自搜索结果，主文页面正文抓取失败，仅得评论区】https://testing.googleblog.com/2020/08/code-coverage-best-practices.html 。GTAC 2016 有相反观点，认为覆盖率仍是测试有效性的强预测因子、变异分数成本高【未核实】。**业界并无定论，不宜写死数值** |
| "有测试"但测试不断言或被跳过 | 高 | OSPS 只要求"至少运行一个自动化套件"（QA-06.01），也不规定质量；我们尺子的"检查能失败"可补这一点【推断】 |
| Lighthouse 分数 | 中：`warn` 级不使 CI 失败，容易成摆设 | Lighthouse CI 官方区分 `warn`/`error`【原文】 |
| 文档/政策类（QA-06.03 "有政策"）| 中：写一段话即达标 | OSPS 自己放在 L3，不当入门要求【原文】 |
| 全开 lint 规则 | 中：噪音会让人忽略 | Clippy 官方说 restriction 组不要整组启用【原文】 |
| 人工审批（QA-07.01）| 对 AI 自动合并场景是反的：条款本意是"非作者人工"，agent 自动合并时需另行定义 | 【推断】 |

## 5. 回答问题 3：现成的"通用基线 + 按栈补充"做法

- **OSPS Baseline**：通用基线，按成熟度分层（L1/L2/L3）；"生态"以示例出现。适合直接借鉴"按场景分级而非按语言分级"。【原文】
- **Scorecard**：通用检查为主，在 Fuzzing、Pinned-Dependencies 处写入个别语言特例。这就是"通用 + 少量按栈例外"的现成样本。【原文】
- **SLSA**：规范只定结果，实现留给"生态系统或组织"自定。【原文】
- **各语言官方文档**（Go modules、Gradle locking、Clippy、PyPA）：各自说明本栈如何达成通用结果，天然就是"按栈补充层"，但它们彼此不构成统一清单。【推断】
- 没找到：一份把"各语言必备检查"统一列出的权威跨语言标准。【推断：本次检索未发现；不排除遗漏】

## 6. 回答问题 4：对我们尺子的建议

**总体：坚持"只写结果"作为必须层，不按技术栈约束到具体手段。** 理由：
1. 权威跨栈标准（OSPS、SLSA、Scorecard、Google review、DORA）都是这条路线，我们不是异类。
2. 点名工具会过时（例如 SLSA v1.0 已 Retired、PyPA 对工具的推荐在不同年份差异大、pylock.toml 各工具支持仍不齐）。
3. 点名工具反而增加"装个工具就算过"的做样子风险。

**增加一个"按栈达成示例"附录，明确标为"示例、非必须"。** 作用是帮评估者（人或 agent）识别"这个栈里什么算达成"，避免把 Go 仓库因没有 `package.json` 判负。

**增加一个短的"建议层"**，收纳性能、a11y、可观测等对产品性质敏感的条目，由仓库自行声明是否适用。

### 6.1 候选条款（每栈 3–8 条）

标记：【必】= 适合进必须层（写成结果）；【建】= 只适合建议层；括号内是达成示例。

**通用（全栈）**
1. 【必】合并前有确定性检查入口且能失败（`make test` / `npm test` / `cargo test`；OSPS 术语表亦举这些例子）
2. 【必】依赖锁定 + 依赖清单（go.sum、gradle.lockfile、pylock.toml、package-lock 等）
3. 【必】密钥不入库
4. 【必】检查文档说明怎么跑（OSPS QA-06.02）
5. 【建】已知漏洞扫描随 PR 自动运行（对"自动合并"档升必须）
6. 【建】变异测试或"检查能失败"的演示，作为覆盖率的替代证据

**前端 / Web（TS/JS）**
1. 【必】类型检查（若仓库用 TS）与构建在 CI 通过（tsc、`next build`）
2. 【必】单测入口
3. 【建】lint（含 a11y 规则）
4. 【建】E2E 冒烟（关键路径）
5. 【建】性能预算：`error` 级 Lighthouse CI 或 bundle 体积上限；阈值由产品自定
6. 【建】Core Web Vitals 线上上报与告警（现场数据而非合并门槛）
7. 【建】依赖审计

**后端 / 服务**
1. 【必】配置与密钥外置（12-Factor III）
2. 【必】数据库迁移可重复执行、与应用发布分离（12-Factor XII 的延伸【推断】）
3. 【必】回滚路径（SRE Launch Checklist 的故障转移与回退）
4. 【建】健康检查端点、优雅关闭（12-Factor IX）
5. 【建】日志/指标/追踪（12-Factor XI、PRR 的埋点与监控）
6. 【建】API 契约（OpenAPI）与契约测试【未核实：本次无成文出处】
7. 【建】金丝雀/分阶段发布（SRE）

**Python**
1. 【必】`pyproject.toml` 声明项目与依赖入口
2. 【必】锁定（pylock.toml 或工具原生锁文件）
3. 【建】类型检查与 ruff 一类 lint/format【未核实】
4. 【建】测试在干净虚拟环境中可跑

**Go**
1. 【必】`go.mod` + `go.sum` 入库（官方明确）
2. 【必】`go vet`（`go test` 默认带）或等价静态检查在 CI
3. 【建】`go mod tidy` 无差异检查
4. 【建】staticcheck / golangci-lint【未核实，仅第三方】
5. 【建】fuzz（Scorecard 认 Go 原生 fuzz）

**Rust**
1. 【必】`Cargo.lock`（对二进制项目）【推断，本次未核原文】
2. 【必】`cargo test` 入口
3. 【建】clippy 警告即失败（`build.warnings=deny`）与 `cargo fmt --check`
4. 【建】库项目对照 API Guidelines（仅发布库时）

**Java / Kotlin**
1. 【必】依赖锁定（Gradle `gradle.lockfile` 默认模式即不一致失败；Maven 同理需另查【未核实】）
2. 【必】`./gradlew test` 或 `mvn test` 单一入口
3. 【建】静态分析与格式检查（Checkstyle/SpotBugs/spotless 等）【未核实】

**Shell**
1. 【建】ShellCheck 在 CI（仓库含大量脚本时升必须）
2. 【建】脚本有 `set -euo pipefail` 等约定【未核实，非本次来源】

### 6.2 不建议写成必须的条目

- 覆盖率百分比阈值（见第 4 节）。如要用，只写"覆盖率下降要可见"，不写固定数值。
- Core Web Vitals 具体数值作为合并门槛（它们是线上真实用户指标）。
- 任何具体工具名。
- OSPS QA-07.01 的"非作者人工审批"：对 agent 自动合并场景需另行定义，不要原样照搬。

## 7. 本次未能核实或覆盖不足

- Google 覆盖率博客主文页面正文未抓到，结论来自搜索摘要中的引文。
- OSPS 页面内 BR-01/02 未读到；标题不全的条目我只写了要点。
- 未取到：npm audit、WCAG/axe、OpenAPI、Maven 等官方页面；Python 类型检查官方依据；go.dev 对 vet/staticcheck 的官方建议。
- SLSA 抓到的是已 Retired 的 v1.0，v1.2 的 Source 相关内容未核。
- DORA 官方页面本次只看到搜索摘要。

## 8. 来源

- OSPS Baseline https://baseline.openssf.org/versions/2026-02-19
- OpenSSF Scorecard checks https://github.com/ossf/scorecard/blob/main/docs/checks.md
- SLSA v1.0 levels（Retired）https://slsa.dev/spec/v1.0/levels
- The Twelve-Factor App https://12factor.net/
- Google SRE Book, Launch Coordination Checklist https://sre.google/sre-book/launch-checklist/
- Google SRE Book, Evolving SRE Engagement Model（PRR）https://sre.google/sre-book/evolving-sre-engagement-model/
- Google Engineering Practices, Reviewer standard https://google.github.io/eng-practices/review/reviewer/standard.html
- Google Testing Blog, Code Coverage Best Practices https://testing.googleblog.com/2020/08/code-coverage-best-practices.html
- Next.js production checklist https://nextjs.org/docs/app/guides/production-checklist
- web.dev Core Web Vitals 阈值 https://web.dev/articles/defining-core-web-vitals-thresholds
- Lighthouse CI configuration https://github.com/GoogleChrome/lighthouse-ci/blob/main/docs/configuration.md
- Go modules 依赖管理 https://go.dev/doc/modules/managing-dependencies
- Gradle dependency locking https://docs.gradle.org/current/userguide/dependency_locking.html
- Clippy usage https://doc.rust-lang.org/clippy/usage.html
- Rust API Guidelines checklist https://rust-lang.github.io/api-guidelines/checklist.html
- ShellCheck wiki https://github.com/koalaman/shellcheck/wiki/Home
- PyPA pyproject.toml 指南 https://packaging.python.org/guides/writing-pyproject-toml/
- pylock.toml 规范 https://packaging.python.org/specifications/pylock-toml/
- PyPA 工具推荐 https://packaging.python.org/en/latest/guides/tool-recommendations/
- Google Cloud DevOps / DORA https://docs.cloud.google.com/architecture/devops
