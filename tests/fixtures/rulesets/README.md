# 尺子夹具

| 文件 | 是什么 |
| --- | --- |
| `toy-base.json` | 玩具尺子，只用于测试引擎（3 档、6 条），不是真实内容 |
| `autopr-onboarding-2.0-basic.trial.json` | **试转写**：autopr 接入标准 v2.0 基础档的 15 条（G1–G7、V1、V2、D1、D2、E1、K1、R1、R2），`readiness-tool` 2026-11-19 按 `onboarding-standard-v2.md` §3、§4、§5.3 与信箱 #21538 的口径写成。**正式版归 `autopr-standard`**，到了以后替换本文件，差异逐条确认 |

## 试转写的核对表

`tests/test_trial_ruleset.py` 把下表写成了代码，逐条断言。

| 条款 | 档位与强度 | 范围 | 适用 | 判定方式 → 探针 |
| --- | --- | --- | --- | --- |
| G1 | 基础 必须 | 仓库 | 全部 | 自动 → `github.repo` |
| G2 | 基础 必须（不可 N/A、不可豁免） | 仓库 | 全部 | 自动 → `github.effective_branch_rules` |
| G3 | 基础 必须 | 仓库 | 全部 | 自动 → `workflow.pr_runs_check` |
| G4 | 基础 必须 | 仓库 | 全部 | 自动 → `github.main_ci_green`（336 小时） |
| G5 | 基础 必须（不可 N/A、不可豁免） | 仓库 | 全部 | 自动 → `github.secret_scanning` |
| G6 | 基础 必须（不可 N/A、不可豁免） | 仓库 | 全部 | 自动 → `github.workflow_permissions` + `workflow.no_dangerous_triggers` |
| G7 | 基础 必须 | 仓库 | 全部 | 自动 → 三个 `config.parses` + `registry.owner_registered` |
| V1 | 基础 必须 | 仓库 | 全部 | 接口 → `entry.run check` |
| V2 | 基础 建议 | 仓库 | 插件、前端 | 接口 → `entry.run check --changed` |
| D1 | 基础 必须 | 仓库 | 全部 | 声明 → 指令文件提到 check + 自评 + 裁决 |
| D2 | 基础 建议、标准 必须 | 仓库 | 全部 | 声明 → 自评 + 裁决 |
| E1 | 基础 必须（无第三方依赖时 N/A，无需理由） | 应用 | 全部 | 自动 → `ecosystem.has_dependencies` 为条件，`ecosystem.lockfile_installed` |
| K1 | 基础 建议 | 仓库 | 插件、前端 | 声明 → 自评 + 裁决 |
| R1 | 基础 必须 | 仓库 | 全部 | 声明 → `risk.template_paths_kept` + 自评 + 裁决 |
| R2 | 基础 建议、标准 必须 | 应用 | 全部 | 声明 → 自评 + 裁决 |

门槛：必须全满足 + 建议 ⌊0.8 × 适用数⌋（用户还在它和"每档最多缺 1 条"之间选）；N/A 过半判未达到；空档判未达到。信任上限：未达标 L0、基础 L2、标准 L3、高档 L4。

## 和标准原文不完全一致、需要 `autopr-standard` 确认的地方

1. 只转了基础档的 15 条；标准档、高档的条款不在本文件里，所以本文件的标准档、高档都是空档，按规则判未达到——这正是想要的（试转写不应让任何仓库拿到 L3 以上）。
2. D1 的确定性部分只查"指令文件（CLAUDE.md 或 AGENTS.md）里出现 check"，三件事是否齐全交给裁决。
3. G2、G5、G6 设了 `na_allowed: false`。标准只说它们不可豁免，没说不可 N/A；我认为安全底线也不该 N/A，待确认。
4. `since` 写 `2.0.0`，没写 `enforce_from`：v2.0 还没批准，批准日未知（#21538 说 34 条的 since / enforce_from 都写批准日）。
