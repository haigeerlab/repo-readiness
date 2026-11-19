# 04 成熟工具里的规则集继承、预设与条件套用

调研日期：2026-11-19。标注：【原文】= 已抓取官方文档并核对（附 URL）；【未核实】= 未能从官方页面确认；【推断】= 我的归纳。

## 一、结论先说

1. **组合方式有四种**，成熟工具几乎都是混用：
   - 继承链（TypeScript `extends`、Stylelint `extends`）
   - 数组叠加，后者覆盖前者（ESLint flat config、MegaLinter `EXTENDS`）
   - 条件匹配（ESLint `files`、pre-commit `files/types`、Kyverno `match/exclude`、Renovate `packageRules`）
   - 命名预设，可远程、可固定版本（Renovate `config:recommended` / `github>org/repo#tag`、CodeQL suites）
2. **"下层只能收紧不能放宽"在配置类工具里几乎没人做。** 配置类工具默认"后写的覆盖先写的"，放宽、关闭都允许（Stylelint 用 `null` 关规则）。真正做"只增不减"的是平台策略类：
   - GitHub rulesets：多个 ruleset 聚合，只会"更严，不会更松"。
   - Semgrep：同一规则出现在多个 policy 时取最高 mode（Block > Comment > Monitor）。
3. **远程引用的安全共识**：按 tag 固定不安全，因为 tag 可被移动。要固定到完整 commit SHA（GitHub 官方安全指南的建议；2025-03 tj-actions 事件是实证）。可读性靠"SHA + 注释写原 tag"（pre-commit `--freeze`）。
4. **技术栈自动检测**：Renovate 按文件名模式、Semgrep 按语言、GitHub CodeQL 默认配置按语言做检测，并且都留了手动覆盖口（`enabledManagers`、编辑语言列表）。**检测错误的兜底**就是"仓库显式声明优先于检测"。
5. **对我们的建议（见第四节）**：一份 `base` 加若干 `stack` 尺子，用**"扁平数组 + 条件 `applies`"**组合，而不是深继承链。同 id 条款在后层出现时，**默认不允许放宽**，只能收紧或增加；放宽必须走仓库显式的、带理由和到期日的 `waivers`。尺子引用必须 `id@version` 加 `sha`，并带宽限期字段。

## 二、对比表

| 机制 | 组合方式 | 冲突怎么解 | 能放宽/删除吗 | 条件套用 | 版本固定 |
|---|---|---|---|---|---|
| ESLint flat config | 数组叠加；`extends` 可引用其他配置 | 后面的对象覆盖前面的 | 能（后面改成 off） | `files`/`ignores` glob；无 `files` 的对象作用于所有被其他对象匹配的文件 | 靠 npm 版本 |
| TypeScript `extends` | 继承链 | 子覆盖父；`files/include/exclude` 整体替换，不合并 | 能 | 无 | 靠 npm / 路径 |
| Stylelint | `extends`（可数组） + `overrides` | 数组后者覆盖前者；本地覆盖 extends | 能，规则设 `null` | `overrides[].files` | 靠 npm |
| Prettier | 无 `extends`；import 后展开 | 展开后自己写的覆盖 | 能 | `overrides[].files` | 靠 npm |
| Renovate | `extends` 预设，可嵌套、带参数 | 本地 `ignorePresets` 优先于预设的；`packageRules` 后者覆盖前者（仅 `fetchChangeLogs` 一处有原文） | 能（`ignorePresets`） | `packageRules` 匹配；manager 按文件名模式检测 | `github>org/repo#tag` |
| pre-commit | 多个 `repos` 条目，各自 `rev` | 无冲突概念 | 能（移除条目或 `exclude`） | `files`/`types`/`exclude` | `rev` 要求不可变 tag 或 SHA；`--freeze` 转 SHA |
| Semgrep | 多个 ruleset / policy 叠加 | 同规则取最高 mode；直接加规则可覆盖 ruleset 继承来的 mode | 能（Disable）；多 policy 间"取最严" | 按检测到的语言只跑相关规则 | 托管侧，无 per-repo 固定【未核实】 |
| CodeQL | suites（default ⊂ security-extended ⊂ security-and-quality）加 packs | workflow 的 queries 默认**替换**配置文件的，加 `+` 才叠加 | 能（换 suite） | 语言 matrix | pack 用 semver 范围；锁文件 `codeql-pack.lock.yml` |
| OPA bundles | 多 bundle，各自声明 `roots` | roots 不重叠，同 manifest 内重叠报错；跨 bundle 加载顺序不保证 | 不适用 | 无 | manifest `revision`；支持签名 |
| Kyverno | 每条策略自带 `match/exclude` | 资源必须满足 match 且不被 exclude | 能（exclude） | `kinds`/namespace/labels；`any`=OR、`all`=AND | 无【未核实】 |
| GitHub rulesets | 多 ruleset 聚合 | **最严者生效**；无优先级 | **不能放宽**（只能 bypass 名单） | 按仓库名/属性匹配（org 级） | 无 |
| 可复用 workflow | `uses: o/r/.github/workflows/x.yml@ref` | 无 | — | — | ref 可为 SHA/tag/分支；推荐 SHA |
| MegaLinter | `EXTENDS` 远程多文件 | 后面的文件优先 | 能（`DISABLE_LINTERS`） | 默认全开，按描述符开关 | URL，无内置固定【未核实】 |

## 三、逐个核实

### 3.1 ESLint
- flat config 是一个对象数组，多个对象匹配同一文件时"later objects overriding previous objects when there is a conflict"。【原文】https://eslint.org/docs/latest/use/configure/configuration-files
- `files`/`ignores` 用 minimatch。没有 `files` 的对象作用于其他对象匹配到的所有文件；只含 `ignores` 的对象是全局忽略。【原文】同上
- `extends` 可引用字符串、对象或数组；文档建议总是和 `files` 配对，否则被继承的配置可能作用于全部文件。【原文】同上
- flat config 没有 cascade，相当于恒为 `root: true`；旧 eslintrc 按目录层级叠加并带 `overrides`。【原文】https://eslint.org/docs/latest/use/configure/migration-guide（页面没讲为什么改，原因【未核实】）
- 【推断】对我们的启发：条件匹配（`files`）比目录层级继承更好推理；"没写条件就作用于全部"是常见踩坑点，条款文件里要么强制写 `applies`，要么明确默认值。

### 3.2 Renovate
- 预设来源：`github>owner/repo`（读 `default.json`）、`github>owner/repo:name`、`local>`、`config:recommended`、HTTP URL。`npm:` 预设已弃用。【原文】https://docs.renovatebot.com/config-presets/
- 固定版本：`github>abc/foo#1.2.3` 以 `#` 加 tag；不写则用默认分支。相对引用继承引用方的 tag。【原文】同上。页面示例只演示 tag，没有 SHA 示例，Renovate 是否支持 `#<sha>` 【未核实】。
- `ignorePresets` 要用带 tag 的绝对解析形式；仓库自己的 `ignorePresets` 优先于预设里的。【原文】同上
- 预设能嵌套；某个预设的相对引用解析失败，会让所有 extends 它的仓库配置报错，官方建议在 CI 用 `renovate-config-validator` 校验预设仓库。【原文】同上（一个对我们有用的教训：尺子仓库自己要有 CI 校验）
- `extends` 数组顺序谁覆盖谁：该预设页和 configuration-options 的已读部分都没明说。【未核实】
- manager 自动检测：每个 manager 带默认 `managerFilePatterns`，按仓库文件列表匹配；`enabledManagers` 白名单；自定义 pattern 是追加不是替换；`ignorePaths` 排除。【原文】https://docs.renovatebot.com/modules/manager/ 。这是"按文件特征自动选规则 + 显式覆盖"的最直接先例。
- `packageRules` 的条件组合语义这次没读到正文。【未核实】

### 3.3 Semgrep / CodeQL
- Semgrep（legacy policies 模型，已被 Unified Policies 取代）：ruleset 是按语言/框架分的规则组；加 ruleset 会给所有规则设默认 mode，之后新增规则以同样 mode 加入；单条规则可以建例外；Semgrep 检测仓库语言，只跑相关规则；同一规则出现在多 policy 时取最高 mode（Block > Comment > Monitor）。【原文】https://docs.semgrep.dev/semgrep-code/policies 。Unified Policies 的新语义【未核实】。
- CodeQL suites 是嵌套递进的：security-extended 在默认基础上加规则，security-and-quality 再加。`queries` 用 `uses` 指向文件/目录/.qls；workflow 里指定的 queries/packs 默认**替换**配置文件里的，前缀 `+` 才合并。【原文】https://docs.github.com/en/code-security/code-scanning/creating-an-advanced-setup-for-code-scanning/customizing-your-advanced-setup-for-code-scanning
- 语言通过 matrix 控制，可增删。【原文】同上。pack 带 semver 范围，`codeql-pack.lock.yml` 记录精确版本，应入库、不手改。【原文】https://docs.github.com/en/code-security/codeql-cli/using-the-advanced-functionality-of-the-codeql-cli/creating-and-working-with-codeql-packs
- 【推断】"替换 vs 合并"默认值不同会让人困惑，我们必须在格式里写死一种，并且显式。

### 3.4 pre-commit
- `repo` + `rev`；`rev` 应是不可变 ref（tag 或 SHA），不支持分支名和 HEAD。`autoupdate` 把 `rev` 推到最新 tag；`--freeze` 把 tag 换成完整 SHA，并留注释 `# frozen: v2.4.0`。【原文】https://pre-commit.com/
- 条件：`files`/`exclude` 是 Python 正则；`types`（AND）/`types_or`（OR）；三者一起按 AND 求值。【原文】同上
- 页面没说 tag 被移动的情形。【原文】标注"文档未提"。

### 3.5 Prettier / Stylelint / tsconfig
- tsconfig：基础配置先加载，继承者覆盖；`files/include/exclude` 整体覆盖而非合并；`compilerOptions` 按项合并（由示例推出）；相对路径相对原文件解析；不允许循环引用。【原文】https://www.typescriptlang.org/tsconfig/#extends 。数组形式 extends 页面未读到。【未核实】
- Stylelint：`extends` 可数组，后项覆盖前项；`rules` 逐条叠加；设 `null` 关规则；`overrides[].files` 按文件套用，后面的 override 更高优先。【原文】https://stylelint.io/user-guide/configure/
- Prettier：没有 `extends`，共享配置是 npm 包，在自己的配置里 import 后展开。搜索结果还提示展开会整体替换 `overrides` 数组，需要手动拼接，该点官方未证实。【搜索摘要，未核实】https://prettier.io/docs/sharing-configurations
- 【推断】tsconfig 的"数组字段整体替换、对象字段按项合并"是个典型陷阱。我们的条款是"按 id 对齐的列表"，要明确规定按 id 合并，不是按数组位置。

### 3.6 OPA / Conftest / Kyverno
- OPA bundle：manifest 有 `revision` 字符串；支持签名（`.signatures.json` + JWT）；多 bundle 共存靠各自声明 `roots`（data 前缀所有权），同一 manifest 内 roots 重叠会报错，跨 bundle 加载顺序不保证。校验失败则继续使用旧 bundle。【原文】https://www.openpolicyagent.org/docs/management-bundles
  - 【推断】"每个包声明自己拥有的命名空间，互不重叠"是避免同 id 冲突的另一条路：冲突不去解，在设计上让它不可能发生。
- Conftest：可从 HTTPS、git（`git::`+`//` 子目录）、OCI 拉取策略。【原文】https://www.conftest.dev/sharing/ 。版本固定与命名空间合并该页没讲。【未核实】
- Kyverno：`match`/`exclude`，`any`=OR、`all`=AND，字段间 AND、列表内 OR；资源须满足 match 且不被 exclude；`kinds` 必填。【原文】https://release-1-18-0.kyverno.io/docs/policy-types/cluster-policy/match-exclude/ 。Audit/Enforce 的细节本次没读到。【未核实】
  - 【推断】`match` + `exclude` 是最清楚的适用范围表达，且 OR/AND 规则固定、可预期。

### 3.7 GitHub rulesets 与 reusable workflow
- Rulesets：规则聚合，无优先级；同一规则定义不同则"most restrictive version"生效；与分支保护并存且全部生效；org 级 ruleset 只有 org owner 能编辑；可按仓库名、属性（如 `props.team:infra`）动态选择；只能通过 bypass 名单豁免。【原文】https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets 、https://docs.github.com/en/organizations/managing-organization-settings/creating-rulesets-for-repositories-in-your-organization 。org 页没提"Evaluate"状态，其存在【未核实】（我记忆中有，但未从这两页确认）。
  - 这是"下层只能收紧"最干净的先例：不提供放宽的通道，只提供"谁能绕过"的通道。
- Reusable workflow：`{owner}/{repo}/.github/workflows/{file}@{ref}`，ref 可为 SHA、tag、分支；同名 tag 与分支时 tag 优先；文档称 SHA 最安全。【原文】https://docs.github.com/en/actions/sharing-automations/reusing-workflows
- 安全指南：建议用完整 commit SHA 固定；tag 在仓库被攻破时可被移动或删除；SHA 要确认来自原仓库而非 fork；锁文件优于 SHA 固定；Dependabot 能更新 SHA 固定，但不会对 SHA 固定的 action 发安全告警。【原文】https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions

### 3.8 版本固定的安全教训
- 2025-03 tj-actions/changed-files 事件（CVE-2025-30066）：攻击者把多个版本 tag 重指向恶意 commit，按 tag 引用的 workflow 执行了恶意代码，按 SHA 固定的不受影响。【搜索摘要，多个二手来源一致，未逐个核对原始公告；入口原因各来源不一致】例如 https://www.stepsecurity.io/blog/harden-runner-detection-tj-actions-changed-files-action-is-compromised 、https://snyk.io/jp/blog/reconstructing-tj-actions-changed-files-github-actions-compromise/
- 注意：SHA 固定只在"选的那个 SHA 本身是干净的"时有效。【搜索摘要】
- 【推断】我们的尺子会告诉仓库"该做什么"，也会带"探针"（可能是可执行的检查）。如果探针可执行，则尺子等同于供应链代码，必须按 SHA 固定。即便探针只是声明式（文件存在、字段值），被篡改的尺子也能让整个组织的评分被操纵，同样值得固定。

### 3.9 技术栈自动检测与兜底
| 工具 | 检测依据 | 覆盖方式 |
|---|---|---|
| Renovate | 每个 manager 的 `managerFilePatterns` 对文件列表匹配 | `enabledManagers`、`enabled:false`、追加 pattern、`ignorePaths` |
| Semgrep | 检测每个仓库的语言 | policy 里按规则/ruleset 例外 |
| CodeQL 默认配置 | 默认按支持的语言设置 | 可编辑语言列表；检测不到语言时安全降级（不扫描、不耗分钟）。如何检测页面未说明【未核实】 |
| MegaLinter | 页面未说明扩展名映射【未核实】；默认全部启用 | `ENABLE`、`DISABLE`、`ENABLE_LINTERS`、`DISABLE_LINTERS`、`DISABLE_ERRORS_LINTERS` |

【推断】共同模式：**检测只负责"提议"，仓库显式声明负责"定案"**，并且有"白名单（只启用这些）"与"黑名单（关掉这个）"两种口。

monorepo 下的多栈：以上工具都按"文件路径模式"工作，即可天然处理不同子目录套不同规则（ESLint `files`、Renovate 按文件名匹配、Stylelint `overrides[].files`）。【推断】我们的做法是让每个"栈尺子"声明自己的 `detect`（文件特征，相对路径 glob），并允许仓库用 `scopes` 把路径映射到栈。

## 四、给我们的建议与格式草图

### 4.1 设计取舍
1. **用"扁平清单 + 条件"，不用深继承链。** 只允许一层：`base`（通用）+ N 个 `stack`；stack 之间不继承，避免菱形和覆盖顺序之争。理由：tsconfig/eslintrc 的链式、层级继承是主要认知负担来源；ESLint 自己转向了单数组加 `files`。【推断】
2. **同 id 冲突规则**（先写死，别让后层静默改写）：
   - 同一 id 只能在**一个**尺子里**定义**；其他层要调整只能用 `tighten`（收紧）。**默认不允许放宽、不允许删除。**这对齐 GitHub rulesets（"more restrictive, never less"）和 Semgrep（取最高 mode），OPA 的 roots 也是"让冲突在设计上不发生"的思路。
   - "收紧"的偏序要先定义：档位只升不降；`suggested -> required` 可以，反之不行；适用范围只能缩小、不能扩大？（见开放问题）
   - 放宽只通过仓库自己的 `waivers`：必须写 id、理由、到期日，且在评分报告里单列"已豁免"，不能让它悄悄消失。这相当于 rulesets 的 bypass 名单，而不是 Stylelint 的 `null`。
3. **适用范围用 `applies`（`match` + `exclude`）**，语义照 Kyverno：字段间 AND、列表内 OR，`exclude` 优先。
4. **检测只提议，声明定案。**仓库里 `stacks` 显式写出就跳过检测（等价于 `enabledManagers` 白名单）；不写则用检测结果，报告里要打印"检测到了什么、依据哪些文件"，以便人发现误判。加 `disableStacks` 作黑名单口。
5. **引用必须同时带版本和 SHA**，tag 仅作可读注释（学 pre-commit `--freeze`）。尺子仓库自己要有 CI 校验格式（学 Renovate `renovate-config-validator`）。
6. **宽限期做在尺子里**，而不是仓库里：条款带 `since`（引入版本）和 `enforceFrom`（日期）。在 `enforceFrom` 之前，该条款即使是 `required` 也只按"建议"计分并告警。这样尺子升级时，已固定旧版本的仓库不会被突然判不合格，升级者提前看到后果。【推断】本次没有找到哪个成熟工具有完全对应的"条款级宽限期"字段；最接近的是 Semgrep 的 Monitor -> Comment -> Block 渐进模式。

### 4.2 最小格式草图（字段名级别）

尺子文件（`ruleset.json`）：
```json
{
  "$schema": "https://…/ruleset.schema.json",
  "id": "base",                  // 尺子 id，全局唯一
  "kind": "base",                // base | stack
  "version": "1.4.0",
  "detect": {                    // 仅 stack 用：检测规则
    "anyOf": ["package.json", "pnpm-lock.yaml"],
    "allOf": [],
    "excludeIfPresent": []
  },
  "clauses": [
    {
      "id": "base.readme-exists",   // 前缀 = 尺子 id，天然避免撞名
      "tier": "L1",                 // 档位
      "level": "required",          // required | suggested
      "applies": { "match": {"paths": ["."]}, "exclude": [] },
      "probe": { "type": "file-exists", "path": "README.md" },
      "fix": "补一个 README.md，至少说明如何运行和测试",
      "since": "1.0.0",
      "enforceFrom": "2026-12-31"   // 宽限期，可空
    }
  ],
  "tighten": [                      // 仅允许对"别的尺子的 id"做收紧
    { "id": "base.readme-exists", "level": "required", "tier": "L1" }
  ]
}
```

仓库声明（`.repo-readiness.json`）：
```json
{
  "extends": [
    { "ruleset": "org/rulesets/base",      "version": "1.4.0", "sha": "<40 位 commit SHA>" },
    { "ruleset": "org/rulesets/frontend",  "version": "2.1.0", "sha": "<sha>" }
  ],
  "stacks": "auto",                 // auto | 显式数组 ["frontend","python"]
  "disableStacks": [],
  "scopes": [                       // monorepo：路径 -> 栈
    { "path": "apps/web", "stacks": ["frontend"] },
    { "path": "services/api", "stacks": ["python"] }
  ],
  "waivers": [
    { "id": "frontend.e2e-tests", "reason": "…", "expires": "2027-03-01", "scope": "apps/web" }
  ]
}
```

合并算法（四步，可写进 schema 说明）：
1. 解析 `extends`，校验 `sha` 与内容一致，取得各尺子。
2. 决定栈：显式 `stacks`/`scopes` > 检测；报告输出检测依据。
3. 按 id 合并：同 id 只有一个定义；`tighten` 只允许升级；发现放宽即报错（不是静默接受）。
4. 套 `applies`，扣除未过期的 `waivers`，按 `enforceFrom` 判定当日是否生效。

### 4.3 开放问题（交给你定）
- "适用范围收紧"是否也禁止扩大？建议禁止扩大、允许缩小的反向——但缩小范围本身是放宽。因此建议 `tighten` 里**不允许改 `applies`**，只允许改 `level/tier`。
- 同一仓库同时套两个栈尺子、且两个栈尺子定义了语义相近但 id 不同的条款，是否要有 `supersedes`？建议先不做，靠 id 前缀和评审避免。
- `probe` 是否允许可执行脚本？允许的话必须把尺子按"代码依赖"对待（SHA 固定、签名、权限最小化）；声明式探针则风险低得多。建议第一版只做声明式探针。
- 宽限期是尺子级还是条款级：我倾向条款级（见上），因为一份尺子里新旧条款的节奏不同。

## 五、来源
- ESLint 配置文件：https://eslint.org/docs/latest/use/configure/configuration-files
- ESLint 迁移指南：https://eslint.org/docs/latest/use/configure/migration-guide
- Renovate 预设：https://docs.renovatebot.com/config-presets/
- Renovate manager：https://docs.renovatebot.com/modules/manager/
- Renovate 配置选项（未读到 packageRules 正文）：https://docs.renovatebot.com/configuration-options/
- pre-commit：https://pre-commit.com/
- TypeScript tsconfig：https://www.typescriptlang.org/tsconfig/#extends
- Stylelint：https://stylelint.io/user-guide/configure/
- Prettier 共享配置：https://prettier.io/docs/sharing-configurations （仅搜索摘要）
- Semgrep policies：https://docs.semgrep.dev/semgrep-code/policies
- CodeQL 高级设置：https://docs.github.com/en/code-security/code-scanning/creating-an-advanced-setup-for-code-scanning/customizing-your-advanced-setup-for-code-scanning
- CodeQL packs：https://docs.github.com/en/code-security/codeql-cli/using-the-advanced-functionality-of-the-codeql-cli/creating-and-working-with-codeql-packs
- CodeQL 默认配置：https://docs.github.com/en/code-security/code-scanning/enabling-code-scanning/configuring-default-setup-for-code-scanning
- OPA bundles：https://www.openpolicyagent.org/docs/management-bundles
- Conftest sharing：https://www.conftest.dev/sharing/
- Kyverno match/exclude：https://release-1-18-0.kyverno.io/docs/policy-types/cluster-policy/match-exclude/
- GitHub rulesets 概览：https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- GitHub org rulesets：https://docs.github.com/en/organizations/managing-organization-settings/creating-rulesets-for-repositories-in-your-organization
- GitHub Actions 安全加固：https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- 可复用 workflow：https://docs.github.com/en/actions/sharing-automations/reusing-workflows
- MegaLinter 配置：https://megalinter.io/latest/configuration/
- tj-actions 事件（二手）：https://www.stepsecurity.io/blog/harden-runner-detection-tj-actions-changed-files-action-is-compromised 、https://snyk.io/jp/blog/reconstructing-tj-actions-changed-files-github-actions-compromise/
