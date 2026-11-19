# Spec：repo-readiness（项目就绪度治理工具）· 第二稿

> 2026-11-19，`readiness-tool` 起草。**状态：已批准（用户 2026-11-19 答复"按建议批准"，含 O1–O10 按建议；O11 届时再定）。** 前提见 [ASSUMPTIONS.md](ASSUMPTIONS.md)，批准时一并确认。
> 第二稿依据：[需求拷问记录](INTERVIEW.md)（5 问）与 [调研汇总](../research/2026-11-19-research-summary.md)。相比第一稿的主要变化：尺子分"通用 + 技术栈"两类并可组合（§3.1）；条款加字段（§3.1）；第一阶段验收线改为"试点真正接进 Auto PR"（§1、§12）；三条接口变成阻塞项（§11）；GitHub 权限不足判 `unknown`（§4.2）。
> 本轮只定"做什么、怎么验收、模块怎么拆、和谁要什么"，不写实现代码。能力图批准后，再按模块逐个细化 Spec。

---

## 1. 目标

**一句话**：拿一把"尺子"（条款文件）去量任意一个代码仓库，告诉它在哪一档、差什么、怎么补；补完再量，直到达标，最后出一份可以交给 Auto PR 的接入结论。

**用户**

| 谁 | 用它做什么 |
| --- | --- |
| 仓库负责会话（如 `agent-relay-owner`） | 本机跑检测，看一屏摘要，拿补丁和操作步骤去补短板 |
| 用户本人 | 审"要人确认"的修复；看接入结论；裁决冲突 |
| Auto PR（`autopr-design` 的流水线） | 准入时读接入结论定信任上限；每周复检读报告决定掉不掉档 |
| 尺子作者（`autopr-standard`） | 按条款文件格式写尺子；用工具的校验命令检查尺子本身写得对不对 |

**成功的样子（第一阶段验收线 = 试点真正接进 Auto PR，见拷问 Q4）**

1. 用 v2.0 条款文件检测 12 个仓库，自动条款的结论和 `assessment-v2.md` 一致，或在差异报告里逐条说明原因；pwa-platform 的 G2 判"达标"（规则集）。
2. agent-relay 走通"检测 → 修复 → 复检"：复检报告能指出哪些条款从 `gap` 变成了 `met`。
3. **agent-relay 达到基础档，接入结论被 Auto PR 准入脚本读取，信任上限定为 L2。** 修复落地的每一项（G2 分支保护、D1"先问"边界、G7 登记文件）都经用户逐一同意。
4. 换一份完全不同的通用尺子，或加一份玩具技术栈尺子，工具不改一行代码就能跑。

**不做**

- 不定条款内容（归 `autopr-standard`）；不做流水线行为：准入、合并、降级执行、开 issue（归 `autopr-design`）。
- 不调用模型；不直接改被测仓库；不对 GitHub 发写请求。
- 第一版不开 PR（见 A14）。

## 2. 能力图（本轮要审的核心）

| 模块 id | 负责什么 | 依赖 |
| --- | --- | --- |
| `clause-format` | 条款文件格式 v1 + JSON Schema；加载与校验（含 YAML 子集解析、内置 schema 校验器）；**通用尺子与技术栈尺子的组合（技术栈解析、同 id 冲突、只收紧）**；`clauses lint` 命令 | — |
| `probes` | 探针运行时（超时、无交互、只读）+ 8 类内置探针 + 生态适配器 + GitHub 平台适配层 | `clause-format` |
| `detect` | 三段式编排：确定性扫描 → 生成待裁决清单 / 读回裁决 → 按门槛规则打分；适用范围、N/A、豁免、应用级取最低 | `clause-format`、`probes` |
| `report` | 检测报告格式 v1 + schema；一屏摘要；退出码 | `detect` |
| `recheck` | 两份报告对比（状态、档位、证据变化）；声明类条款的证据指纹沿用 | `report` |
| `conclusion` | 接入结论格式 v1 + schema；从报告生成结论；结论自校验 | `report` |
| `remedy` | 三类修复：自动（补丁 + PR 草稿）、要确认（精确命令）、只能人做（建议 + 参考） | `report`、`probes` |
| `agent-entry` | Claude Code / Codex 共用的薄 skill：调 CLI、做第二段裁决、讲摘要、逐项征求确认 | 以上全部 |

构建顺序：`clause-format` → `probes` → `detect` → `report` → `recheck`、`conclusion`（可并行）→ `remedy` → `agent-entry`。

依赖只朝一个方向；`detect` 不认识任何具体条款，`probes` 不认识档位和打分。

> 为什么"复检"单列模块而不是"检测"的一个参数：它有自己的消费者（Auto PR 每周复检、负责会话修复后自查）和自己的格式（对比结果），可以单独验收。

## 3. 三份对外格式（双方唯一的衔接面）

三者都带 `schema` 字段写明格式与主版本，都有 JSON Schema（2020-12），放在本仓库 `schemas/`。**只加可选字段不升主版本；字段只增不删；改必填字段或语义升主版本，提前通知并给 30 天过渡**（和接口层契约的规则一致）。

### 3.1 条款文件 `repo-readiness.clauses/v1`

尺子本身。下面是 v2.0 两条条款的写法示意（字段名在 `clause-format` 模块 Spec 里定稿）：

```json
{
  "schema": "repo-readiness.clauses/v1",
  "id": "autopr-onboarding",
  "version": "2.0.0",
  "owner": "autopr-standard",
  "categories": ["plugin", "contract", "frontend", "content"],
  "tiers": [
    { "id": "basic",    "name": "基础档", "rank": 1, "trust_cap": "L2" },
    { "id": "standard", "name": "标准档", "rank": 2, "trust_cap": "L3" },
    { "id": "high",     "name": "高档",   "rank": 3, "trust_cap": "L4" }
  ],
  "below_lowest": { "name": "未达标", "trust_cap": "L0" },
  "gate": {
    "cumulative": true,
    "must": "all",
    "should": { "ratio": 0.8, "rounding": "floor" },
    "na_majority": "not-reached",
    "unknown": "counts-as-gap"
  },
  "waiver": { "max_days": 90, "non_waivable": ["G2", "G5", "G6"] },
  "app_aggregation": "min",
  "clauses": [
    {
      "id": "G2",
      "layer": "general",
      "requirement": "main 上生效的规则同时做到：禁止 force push、禁止删除、变更只能经 PR 合入",
      "guards": "绕过裁判直接改 main",
      "levels": [{ "tier": "basic", "strength": "must" }],
      "scope": "repo",
      "applies": { "categories": "*" },
      "method": "auto",
      "probe": {
        "use": "github.effective_branch_rules",
        "with": { "branch": "main", "require": ["no_force_push", "no_deletion", "pull_request_required"] }
      },
      "remedy": { "class": "confirm", "generator": "github.branch-rules", "hint": "补勾「合并前必须有 PR」，审批人数 0" }
    },
    {
      "id": "R2",
      "layer": "capability",
      "requirement": "写下回滚路径：撤回一次合并要哪些步骤、谁执行、大概多久",
      "guards": "出事临时找办法",
      "levels": [
        { "tier": "basic",    "strength": "should" },
        { "tier": "standard", "strength": "must" }
      ],
      "scope": "app",
      "applies": { "categories": "*" },
      "method": "declare",
      "probe": { "use": "declare", "with": { "key": "R2" }, "then": { "use": "judge" } },
      "remedy": { "class": "manual", "hint": "在指令文件或 docs/ 写回滚步骤", "refs": ["onboarding-standard-v2.md §5.3"] }
    }
  ]
}
```

**两类尺子与组合（第二稿新增）**

- `kind: base`：通用尺子（v2.0 的 34 条）。`kind: stack`：技术栈尺子，多一个 `stack` 字段（如 `frontend`、`shell-plugin`）和可选的 `detect`（按文件特征给出检测提议，如 `anyOf: ["package.json"]`）。
- 仓库在 `readiness.yml` 写 `stacks: [shell-plugin]`，monorepo 可按应用写 `apps.site.stacks: [frontend]`。**以声明为准**；没写才用 `detect` 的结果；不一致时报告列"待确认"，不计分。
- 组合只叠一层：一份 base + 若干 stack；stack 之间不继承。
- 同一条款 id 只能在一份尺子里定义（技术栈条款用前缀，如 `FE1`、`SH1`，前缀由 `autopr-standard` 定）。别的尺子只能写 `tighten`：档位只升、强度只从 `should` 升 `must`；**不能改适用范围，不能放宽，不能删除**。发现放宽 → 加载失败，退出码 2。放宽只能走仓库的豁免。
- 门槛规则（`gate`）、档位、信任上限只在 base 里定义；stack 的条款并入同一套档位计算。
- 技术栈尺子允许必须条款（拷问 Q1）；"每栈不超过 2 条必须"是内容约束，由 `autopr-standard` 定，工具只在 lint 里给警告、不硬拦。

**条款新增字段（第二稿，借鉴 OpenSSF Best Practices Badge 的 `criteria.yml`）**

| 字段 | 含义 |
| --- | --- |
| `rationale` | 为什么有这条（标准里"防什么"之外的背景，可空） |
| `na_allowed`、`na_justification_required` | 能否申请 N/A；申请时是否必须写理由（默认：类别不适用时自动 N/A，其余要理由 + 用户批准，同标准 §9） |
| `since`、`enforce_from` | 引入的尺子版本；从哪天起按设定强度计分。之前按"建议"计并告警——标准 §11 的"新增条款 30 天宽限期"由此计算 |
| `lifecycle` | `active` / `future`（预告，不计分）/ `obsolete`（作废，不计分，保留 id 防复用） |

要点：

- **一个条款 id 可以在多档出现、强度不同**（`levels` 是列表）。v2.0 里 R2、D2 基础档建议、标准档必须，V2 两档都是建议，G11 在通用层和高档表里各出现一次——这些都靠 `levels` 表达，不重复写条款。
- **适用范围**除了类别，还支持条件（"有第三方依赖的"、"有跨仓库接口的"），条件本身也是一个探针。
- **探针可组合**：`all` / `any` / `then`（先确定性取证，再交裁决）。
- 尺子作者用 `repo-readiness clauses lint <file>` 自查：schema、引用的探针是否存在、id 是否重复、档位引用是否有效。

### 3.2 检测报告 `repo-readiness.report/v1`

机器读的 JSON。核心字段：

| 字段 | 说明 |
| --- | --- |
| `repo`、`head` | 被测仓库与 40 位提交 SHA |
| `clauses_ref` | 本次组合用到的每份尺子的 `id`、`kind`、`version`、`sha256`；技术栈来自声明还是检测；声明与检测不一致的清单 |
| `not_evaluated[]` | 本次没有评估的条款及原因（未开 `--exec-entries`、尺子 `future`、权限不足等），借鉴 Scorecard |
| `tool` | 工具版本与自身提交 SHA（自我维护防火墙要用，见 §6） |
| `generated_at`、`baseline` | 生成时间；作为基准的上一份报告的 sha256（可空） |
| `tier`、`apps[].tier` | 仓库档位（= 各应用最低值）与每个应用的档位 |
| `next_tier` | 下一档还差哪几条（必须项清单 + 建议项还差几条） |
| `results[]` | 每条 × 每个作用对象（仓库或应用）：`status`、`evidence[]`（一句话 + 文件:行 / 命令输出摘要 / API 路径）、`missing`（差什么）、`fingerprint`（证据指纹）、`source`（`scan` / `judge` / `carried-over`）|
| `judgment_requests[]` | 本次还没裁决的声明类条款（无交互运行时留在这里） |
| `errors[]` | 探针自身出错（不等于条款不达标） |

人读的一屏摘要（`summary.md`，≤ 30 行）格式示意：

```text
agent-relay @ 3f2a9c1 · 尺子 autopr-onboarding 2.0.0 · 当前：未达标（L0）· 目标：基础档
基础档必须 8/11 · 建议 1/3（需 2）
  ✗ G2  main 未要求"必须经 PR"         → 要确认：1 条命令（repair 里有）
  ✗ G7  缺 readiness.yml、risk-tiers.yml、interface.yml → 可自动：补丁 1 个
  ✗ D1  指令文件没写 autopr/* 例外       → 要确认：改"先问"边界
  ? R1  T3/T4 核对记录待裁决             → 等 agent 裁决
离标准档还差：P1、E2、K3、Q1（必须）…
```

### 3.3 接入结论 `repo-readiness.conclusion/v1`

| 字段 | 说明 |
| --- | --- |
| `repo`、`head` | 结论针对的提交 |
| `tier`、`trust_cap` | 达到的档位，与条款文件里该档的信任上限（照抄，工具不内置对应关系） |
| `apps[]` | 每个应用的档位与上限（是否按应用分别生效，见接口清单 #8） |
| `basis` | 报告的 sha256、条款文件 `id`/`version`/`sha256`、工具版本与 SHA |
| `issued_at`、`valid_until` | 签发时间；有效期（默认等于下次复检周期 + 宽限，具体值和 `autopr-design` 定） |
| `declarations_expire_at` | 声明类条款证据最早的过期日（标准 §10 的 90 天） |
| `waivers[]` | 生效中的豁免及到期日 |
| `default_branch` | 默认分支名（`autopr-design` 要求，#21530） |
| `attestation` | 结论的发布证明：证明它出自允许列表里的发布版工具（具体机制待定，见接口清单 #14） |

结论只陈述事实，不包含任何"流水线该怎么做"。

## 4. 各模块要点与验收

### 4.1 `clause-format`

- 交付：`schemas/clauses.v1.json`；加载器；YAML 子集解析器；内置 schema 校验器；`clauses lint`。
- 验收：
  - v2.0 的 34 条能全部写成 v1 格式并通过 lint（由 `autopr-standard` 转写，见接口清单 #1；我先写一份试转写做格式验证）。
  - 一份玩具尺子（3 档、5 条、不同门槛比例）能被加载、打分正确。
  - `readiness.example.v2.yml`、`interface.example.yml` 能被 YAML 子集解析器正确读出；构造的锚点、多文档、`|` 块等语法明确报错，退出码 2。
  - 组合：base + 一份玩具 stack 能合成；stack 里重复定义 base 的 id、或 `tighten` 试图降强度 / 改适用范围，加载失败，退出码 2；声明 `stacks` 与 `detect` 不一致时进"待确认"、不计分；`enforce_from` 之前的必须条款按建议计。

### 4.2 `probes`

- 内置探针（A12）：`fs`、`config`、`github`、`workflow`、`entry`、`declare`、`judge`、`registry`。
- 生态适配器：`adapters/*.json`，数据驱动，例如：

  ```json
  { "id": "node", "lockfiles": ["pnpm-lock.yaml", "package-lock.json", "yarn.lock"],
    "frozen_install": ["pnpm install --frozen-lockfile", "npm ci", "yarn install --immutable"] }
  ```

- GitHub 平台适配层：所有 `gh api` 调用经一个只发 GET 的封装，可替换为"录制回放"（测试用）。
- 关键判据（需要和 `autopr-standard` 对齐口径，见接口清单 #2）：
  - G2：旧版保护和规则集**逐项取并集**（例如禁 force push 来自旧版保护、必须经 PR 来自规则集，算满足），还是**任一来源单独满足**？两种读法结论可能不同，先按"逐项并集"实现并等确认。
  - G10：重跑率的分子分母（按 run 还是按 workflow；`attempt > 1` 且最终 success 算"重跑就通过"？）；p90 的样本是"必需检查对应的 job"还是整个 run。
  - G4：14 天按 UTC 日历日还是 336 小时。
- **权限与生效状态（第二稿新增，A28）**：探针先判断当前 token 能不能读到需要的设置；读不到（如非管理员 token 读不到部分分支保护、读不到 workflow 默认权限）判 `unknown`，不判 `gap`。规则集只认 `enforcement: active`；`evaluate`、`disabled` 不算生效。规则集的 bypass 名单如实记进证据，是否影响 G2 等 `autopr-standard` 定口径（接口清单 #2）。
- 验收：每个探针有正反用例；以下真实 API 返回录制成夹具：pwa-platform 规则集（G2 `met`）、agent-relay 旧版保护未要求 PR（G2 `gap`）、规则集处于 `evaluate`（G2 `gap`）、权限不足读不到（G2 `unknown`）。

### 4.3 `detect`

- 第 0 步（第二稿新增）：解析尺子组合——读仓库声明的 `stacks`（及各应用的 `stacks`），没写则跑 `detect`；把 base 与对应 stack 合成本次要判的条款集；报告里写明套了哪些尺子、依据是什么、哪些检测结果与声明不一致。
- 三段式：
  1. 确定性扫描：跑全部探针，`method: auto` / `interface` 的条款直接出结论；`declare` 类先取证（读 `readiness.yml` 的自评和引用的证据文件）。
  2. 裁决：对需要判断的条款输出 `judgment-requests.json`（条款、自评、已取到的证据、上一份报告的结论和指纹）。证据指纹没变的，直接沿用上次结论（`source: carried-over`）。agent 写回 `judgments.json`（每条 `met` / `gap` + 一句证据）；CLI 校验：引用的文件存在、行号在范围内、只裁决被请求的条款。
  3. 打分：纯函数，按条款文件的 `gate` 计算；N/A 过半、豁免过期、不可豁免条款、应用取最低都在这里。
- 验收：打分函数对 v2.0 门槛规则有表驱动测试（包括"建议 80% 向下取整"、"N/A 过半判未达到"、"G2 豁免无效"、"应用 2/3 达标时仓库取最低"）；无交互运行（`</dev/null`）不挂起。

### 4.4 `report`

- 交付：`schemas/report.v1.json`、`summary.md` 生成、退出码（A18）。
- 验收：报告通过自身 schema；摘要 ≤ 30 行；`--min-tier basic` 在达标 / 未达标 / 工具出错三种情况下分别退出 0 / 1 / 2，`gh` 未登录退出 3。

### 4.5 `recheck`

- `repo-readiness diff <old.json> <new.json>`：列出状态变化、档位变化、证据变化、新增的 `unknown`。
- 两份报告的条款文件版本不同时，明确标出"尺子变了"，把条款增删和仓库变化分开列。
- 每个档位变化标原因类别：仓库变化 / 尺子变化 / 豁免过期 / 声明过期 / 权限或环境导致 `unknown`。社区同类工具都没有把复检对比当正式输出，这是本工具的差异点，要重点测。
- **掉档信号**（与 `autopr-design` 约定，#21530）：判据只放在这里一处。报告为每条必须的自动条款记录"连续不满足次数"；`diff` 输出 `drop_signals[]`：任一必须的自动条款连续两次不满足，或 G2 / G5 / G6 一次不满足（标准 §10），即给出掉档信号与目标档位。Auto PR 的 degrade 脚本只消费这个信号，不自己比报告。
- 验收：agent-relay 闭环里能看到 G2 / G7 从 `gap` → `met`；尺子换版本时不把"新增条款"误报成"仓库退步"。

### 4.6 `conclusion`

- `repo-readiness conclude <report.json>`：只有报告完整（没有未处理的裁决请求、没有探针错误）时才出结论，否则退出 1 并说明缺什么。
- 验收：结论通过 schema；对报告做任何篡改后，`conclusion verify` 能发现 sha256 不符。

### 4.7 `remedy`

- 三类，类别由条款文件的 `remedy.class` 指定，内容由内置"生成器"产出：
  - **auto**：生成补丁（`*.patch`）+ PR 草稿（正文 markdown，含改了什么、为什么、怎么验）。例：G7 的三个登记文件骨架（从 `readiness.yml` 模板和被测仓库已探到的事实预填）、G9 的 action 按 SHA 固定（SHA 通过 GitHub API 只读解析）。
  - **confirm**：输出精确命令（例如 `gh api -X PUT repos/<o>/<r>/branches/main/protection ...` 的完整参数）、预期变化、怎么撤回。CLI 不执行。
  - **manual**：具体建议 + 条款文件里的参考材料。
- 验收：agent-relay 的 G7 补丁能 `git apply --check` 通过；补丁应用后（在临时副本里）复检该条 `met`。

### 4.8 `agent-entry`

- 一个 skill，两宿主共用：触发语如"检测一下这个仓库的就绪度""能不能接入 autopr"。
- 流程：跑 CLI 第一段 → 自己做裁决并写 `judgments.json` → 跑打分 → 讲一屏摘要 → 对 `confirm` 类逐项问用户，用户明确同意后才执行命令 → 复检。
- 遵守自我维护防火墙：只调用已安装的发布版 CLI（见 §6）。

## 5. 命令（目标形态，实现时定稿）

```bash
repo-readiness clauses lint <clauses.json>
repo-readiness check <repo-path> --clauses <clauses.json> [--app <id>] [--baseline <old-report.json>] \
    [--judgments <judgments.json>] [--exec-entries] [--min-tier basic] --out <dir>
repo-readiness diff <old-report.json> <new-report.json>
repo-readiness remedy <report.json> --out <dir>
repo-readiness conclude <report.json> --out <conclusion.json>
repo-readiness conclusion verify <conclusion.json> --report <report.json>
```

开发命令：

```bash
python3 -m unittest discover -s tests -v      # 全部测试
bin/validate.sh                                # 测试 + 自带 schema 校验 + 夹具一致性
```

## 6. 自我维护防火墙

将来 repo-readiness 自己也被 Auto PR 维护，所以：

- 工具按语义化版本发版，**发版由人做**；每份报告和结论都写入工具版本和自身提交 SHA。
- Auto PR 准入只认"发布版"产生的结论：结论里的工具版本必须在 Auto PR 中心仓库登记的允许列表里（允许列表放哪、谁维护，见接口清单 #7、#14）。
- 本仓库里：`schemas/`、打分函数、内置探针的判据都列为 T4（改它等于换裁判）。

## 7. 项目结构（草案）

```text
bin/repo-readiness          → 启动脚本（调用 python3 -m repo_readiness）
src/repo_readiness/
  cli.py                    → 命令入口
  clauses/                  → 条款文件加载、校验（clause-format）
  yamlsub.py, schema.py     → YAML 子集解析、内置 JSON Schema 校验
  probes/                   → 内置探针；platform/github.py 为平台适配层
  adapters/                 → 生态适配器（JSON 数据）
  detect/                   → 三段式编排与打分
  report/, recheck/, conclusion/, remedy/
schemas/                    → 三份对外格式 + 裁决文件的 JSON Schema
skills/repo-readiness/      → agent-entry 的 SKILL.md
tests/                      → unittest；fixtures/ 放录制的 GitHub 返回和玩具仓库
docs/spec/                  → 本 Spec、ASSUMPTIONS、各模块 Spec
```

## 8. 代码风格

- Python 3.9 语法上限（不用 `match`、不用 3.10 的 `X | Y` 类型写法）；类型标注用 `typing`。
- 打分、对比是纯函数：输入数据结构，输出数据结构，不碰文件和网络。
- 子进程一律经一个封装：

```python
def run(argv: List[str], *, cwd: Path, timeout_s: int, env: Dict[str, str]) -> RunResult:
    """No stdin, no TTY, hard timeout. Timeout maps to exit code 3 (environment not ready)."""
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return RunResult(code=3, stdout="", stderr=f"timeout after {timeout_s}s")
    return RunResult(code=p.returncode, stdout=p.stdout, stderr=p.stderr)
```

- 代码与注释用英文；面向用户的输出（摘要、修复说明）用中文。

## 9. 测试策略

- 框架：标准库 `unittest`，零依赖。
- 层次：
  - 单元：YAML 子集解析、schema 校验、每个探针（正反用例）、打分函数（表驱动）。
  - 夹具回放：GitHub 返回录制成 JSON（pwa-platform 规则集、agent-relay 旧版保护等），探针在回放模式下跑，不依赖网络。
  - 端到端：`tests/fixtures/repos/` 下的玩具仓库 + 玩具尺子，跑完整 `check → remedy → 应用补丁 → check → diff`。
  - 标准答案对照：12 个仓库的初评结论写成期望值，`tests/golden/` 只读跑一遍（需要网络，单独命令，不进默认测试）。
- 每个检查器要能失败：新增的判据都附一个"会失败"的样例（和标准 Q1 同一要求，工具自己先做到）。

## 10. 边界

- **总是**：检测只读；子进程无 stdin、有超时；报告里写清条款文件版本和工具版本；改了格式就同步改 schema 和测试。
- **先问**：改三份对外格式的必填字段或语义（还要通知对方会话）；加任何第三方依赖；执行任何对 GitHub 的写操作；改 agent 指令文件的"先问"边界；`git init`、建远端、推送、发版。
- **从不**：修改被检测的仓库；修改 `autopr-standard`、`autopr-design` 的文件；在工具里写死条款内容或档位 → 上限的对应关系；让模型做打分。

## 11. 跨会话接口清单

规则：凡需要对方提供或配合、或我的改动影响对方的，都经本机信箱告诉对方并设 `expectsReply: true`；发送前先给用户过目，并用 `bridge_agents` 核对收件人仍在登记（2026-11-19 已核对：`autopr-standard`、`autopr-design` 都在）。

第一阶段验收线是"试点真正接进 Auto PR"（拷问 Q4），所以下表 **#4、#5、#7、#18 是阻塞项**：对方不答复，第一阶段无法验收。

| # | 谁需要 | 需要什么 | 谁提供 | 什么时候要 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | 我 | v2.0 的 34 条转写成条款文件格式 v1（`kind: base`） | `autopr-standard`（我先给格式 + 两条示例 + 我的试转写） | `clause-format` 实现前；格式定稿后 | 待发 |
| 2 | 我 | 判定口径：G2"实际生效规则"是逐项并集还是任一来源；**规则集 bypass 名单里有用户本人或 agent 身份时，G2 还算不算满足**；G10 重跑率和 p90 的算法；G4 的 14 天怎么算；G3"调用了 `check`"怎么认（命令字符串匹配还是 workflow 调用包装器）；G6 是否以 Scorecard 判据为准 | `autopr-standard` | `probes` 实现前 | 待发 |
| 3 | 我 | 被测仓库入口的调用方式和退出码 | 已有 `interface-contract.md` v1，**我按它实现，不提修改**；只请确认：检测时跑入口用临时 worktree，是否需要在契约里写进"框架可能在只读副本中调用" | `probes` 的 `entry` 探针实现前 | 待发（仅确认） |
| 4 | `autopr-design` | **【阻塞】** 接入结论格式 v1（§3.3），准入脚本据此定信任上限；还要对方给出准入脚本读取结论的时间 | 我提供格式，对方给时间 | 结论 schema 定稿后立即通知 | 已答（#21530）：字段够用，补 `default_branch` 和结论的发布证明；准入取 min(结论 trust_cap, trust.yml, 降级 issue)，结论缺失 / 过期 / 解析失败 / 工具版本不在允许列表 → L0；`valid_until` 14 天。**时间待用户**：Auto PR 设计未批准、准入脚本未写 |
| 5 | 双方 | **【阻塞】** 每周复检和掉档：谁跑复检（Actions 定时 vs 本机编排会话）、声明类条款在 CI 里无法裁决时是否允许沿用上次结论、谁判"连续两次不满足"（我在 `diff` 里给出信号，还是 degrade 脚本自己比）、谁开 `autopr:readiness-drop`、报告和结论写到仓库哪里 | 和 `autopr-design` 共同定 | `recheck` 实现前 | 已答（#21530）：Actions 定时只复检自动条款，声明类沿用到 90 天；**掉档信号由我在 `diff` 里输出**，degrade 只消费、开 `autopr:readiness-drop`；报告做 Actions artifact，摘要写固定 issue，结论放被测仓库 `.github/autopr/readiness-conclusion.json`（T4，升档走 PR 人合并，掉档靠 drop issue） |
| 6 | 我 | 修复 PR 用谁的身份开、权限边界（设计 Q2） | `autopr-design` | `remedy` 开 PR 功能之前（第一版不开 PR，不阻塞） | 已答：同意第一版不开 PR；身份待用户（设计 Q2） |
| 7 | 双方 | **【阻塞】** 检测脚本放在哪：本仓库发版，Auto PR 中心仓库按 tag + SHA 引用（我的建议），还是拷进中心仓库 | 和 `autopr-design` 共同定，再报用户 | Spec 批准后尽早 | 已答：同意本仓库发版、中心仓库按 tag + SHA 引用；中心仓库未建（设计 Q9，待用户） |
| 8 | 双方 | monorepo 按应用判档后，准入能否按"文件 → 应用"分别设上限（标准 Q-S3）。我的结论里已经按应用给出档位，用不用由对方定 | `autopr-design` | `conclusion` 定稿前 | 已答：用；准入按"文件 → 应用"映射，跨应用 PR 取最低（设计 r6） |
| 9 | 双方 | `verify` 证据存放位置（契约 Q-I2）；P1 检测时我从哪里拿证据清单 | `autopr-design` | P1 探针实现前 | 已答：证据评论 `autopr-evidence:v1`，大产物放 Release 资产 / 对象存储留链接 + sha256；P1 的证据清单直接用 `entry-report.schema.json` 的 `verify` 输出 |
| 10 | `autopr-standard` | **新增**：`readiness.yml` 等 YAML 文件只能用 YAML 子集（A6），请在标准或模板里写明，或接受 JSON 替代 | 我告知，对方确认 | `clause-format` 实现前 | 待发 |
| 11 | 我 | **新增**：同一条款在多档出现、强度不同（R2、D2、V2、G11）的语义确认：按 `levels` 列表理解，每档单独计数 | `autopr-standard` | 转写前 | 待发 |
| 12 | 我 | **新增**：`unknown`（无法判定）在打分里按不满足计，且 G2/G5/G6 一次 `unknown` 算不算"一次不满足就掉档" | `autopr-standard` | `detect` 实现前 | 待发 |
| 13 | 我 | **新增**：G7 要求 owner 在本机信箱登记，CI 里查不到信箱。是否只在本机检测时查、CI 里沿用上次结论 | `autopr-standard` | `probes` 实现前 | 待发 |
| 14 | `autopr-design` | **新增**：自我维护防火墙——报告和结论里带工具版本与 SHA；中心仓库要维护"允许的工具版本"列表 | 我告知，对方定落点 | 结论格式定稿时 | 已答：同意，允许列表放中心仓库，T4 |
| 15 | 我 | **新增**：X1 要读中心仓库的 `contracts.yml`；K4、G12 要读 Auto PR 的纠正事件 issue、晋升 PR、metrics workflow 记录。需要这些的位置、标签名和格式 | `autopr-design` | 标准档 / 高档条款实现前（不阻塞基础档） | 已答：`contracts.yml` 在中心仓库根目录（未建）；纠正事件 issue 标签 `correction` + `correction:<类名>`；晋升 PR 标题 `fix(guard): <类名>`；度量看固定 issue 标签 `autopr:metrics` + 产物 `autopr-metrics.json` |
| 16 | 我 | **新增**：G7 骨架里的 `risk-tiers.yml` 要 `extends` 类别模板，模板在中心仓库；生成补丁时需要模板的位置和版本 | `autopr-design` | `remedy` 实现前 | 已答：草案在 autopr-design worktree 的 `config/risk-tiers.categories.example.yml`（未提交，只读；`extends` 结构不变） |
| 17 | 我 | **第二稿新增**：技术栈尺子的内容——第一批只要**前端**、**Shell 插件**两份（后端 / Go / Rust 不写）；技术栈条款的 id 前缀；"每栈必须条款不超过 2 条、只收'用了就必然该有'的"这条门槛是否接受；`readiness.yml` 加 `stacks` 字段（含按应用写）。调研摘出的候选条款见调研汇总 §1，供参考 | `autopr-standard` | 格式定稿后；基础档试点不依赖技术栈尺子，不阻塞 | 待发 |
| 18 | 双方 | **第二稿新增【阻塞】**：试点仓库对齐——我这边是 agent-relay（接进 Auto PR）+ pwa-platform（只验证不误判）；`autopr-design` 设计 P1 写的是 tier-guard，其 Q15 建议改 agent-relay。双方确认同一个试点后报用户 | `autopr-design` | Spec 批准后立即 | 已答：双方一致 agent-relay 试点、pwa-platform 验证不误判；待用户最终确认 |

## 12. 成功标准（整体）

1. `clauses lint` 通过 v2.0 转写版；玩具通用尺子、玩具技术栈尺子不改代码能跑。
2. 12 个仓库只读检测，自动条款与 `assessment-v2.md` 一致或逐条说明差异；pwa-platform G2 `met`；权限不足、规则集 `evaluate` 两类夹具结论正确。
3. agent-relay 闭环：检测 → 补丁与命令 → 经用户逐项同意后落地 → 复检 → `diff` 显示变化。
4. **agent-relay 达到基础档，接入结论被 Auto PR 准入脚本读取，信任上限 L2**（第一阶段验收线）。
5. 无交互运行（`</dev/null`，无 TTY）不挂起；四种退出码各有测试。
6. 三份对外格式都有 schema，工具自己的输出全部通过自己的 schema。
7. 零第三方依赖：在 `/usr/bin/python3`（3.9.6）和 ubuntu CI 的 python3 上全部测试通过。

## 13. 待决问题

| # | 问题 | 我的建议 |
| --- | --- | --- |
| O1 | 能力图（§2）的模块边界与构建顺序 | 按 §2 |
| O2 | 远端与可见性（A2） | `haigeerlab/repo-readiness`，公开 |
| O3 | CLI 为核心、skill 为薄入口（A4） | 是 |
| O4 | Python 3.9 标准库、零依赖（A5、A6） | 是 |
| O5 | 检测时执行被测仓库入口默认关闭（A10） | 默认关，显式开启，在临时 worktree 里跑 |
| O6 | 修复第一版只出补丁和 PR 草稿（A14） | 是 |
| O7 | 试点 pwa-platform（不误判）+ agent-relay（真正接进 Auto PR）（A19） | 是 |
| O8 | G2 判据按"逐项并集"先实现，等 `autopr-standard` 确认 | 是 |
| O9 | 尺子组合规则：只叠一层、同 id 唯一、只能收紧（A20–A22） | 是 |
| O10 | Python 检查脚本归入 Shell 插件尺子（A24，拷问时未单独表态） | 是 |
| O11 | 若 `autopr-design` 迟迟交付不了准入脚本，第一阶段是否允许临时降为"报告准 + 补丁可用"验收（A27） | 到时再请你定 |

已定（拷问记录见 [INTERVIEW.md](INTERVIEW.md)）：技术栈尺子允许少数必须；只服务本组织；后端 / Go / Rust 只留格式；验收线是试点接进 Auto PR；技术栈以仓库声明为准。
