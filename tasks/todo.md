# 任务清单：repo-readiness

> 计划见 [plan.md](plan.md)。通用验证命令（T1 建好后）：
> - 全部测试：`python3 -m unittest discover -s tests -v`
> - 总校验：`bin/validate.sh`（测试 + 用 `/usr/bin/python3` 再跑一遍 + 自身 schema 校验）
> 每个任务完成的通用标准：新增逻辑有"会通过"和"会失败"两类用例；`bin/validate.sh` 绿；`</dev/null` 下不挂起。

## 阶段 1：地基、纵向切片、结论

- [x] **T1 项目骨架**（S）
  - 做什么：`bin/repo-readiness` 启动脚本、`src/repo_readiness/` 包、`cli.py`（`--version`、子命令分发）、子进程封装 `run()`（无 stdin、超时映射退出码 3）、`bin/validate.sh`、`.gitignore`、`README.md` 一页。
  - 验收：`bin/repo-readiness --version </dev/null` 输出版本、退出 0；未知子命令退出 2；`run()` 超时用例返回 3。
  - 依赖：无。文件：`bin/`、`src/repo_readiness/{__init__,cli,proc}.py`、`tests/test_proc.py`、`README.md`。

- [x] **T2 YAML 子集解析器**（S）
  - 做什么：块状映射、列表、行内 `{}`/`[]`、带引号和不带引号的标量（含日期、布尔、数字的保守识别）、注释；不支持的语法（锚点、别名、多文档、`|`/`>` 块、标签）报带行号的错。
  - 验收：标准侧 `readiness.example.v2.yml`、`interface.example.yml`（拷成测试夹具）解析结果与手写期望一致；6 类不支持语法各有用例，抛出解析错误。
  - 依赖：T1。文件：`src/repo_readiness/yamlsub.py`、`tests/test_yamlsub.py`、`tests/fixtures/yaml/`。

- [x] **T3 内置 JSON Schema 校验器**（S）
  - 做什么：只实现我们 schema 用到的 2020-12 关键字（`type`、`required`、`properties`、`additionalProperties`、`enum`、`const`、`pattern`、`items`、`minimum`/`maximum`、`$ref` 到本地 `$defs`、`oneOf`/`anyOf`），用到未实现的关键字时直接报错（防止"看着通过"）。
  - 验收：标准侧 `entry-report.schema.json` 能被加载并校验正反样例；未实现关键字报错。
  - 依赖：T1。文件：`src/repo_readiness/schema.py`、`tests/test_schema.py`。

- [x] **T4 条款文件格式 v1 + `clauses lint`**（M）
  - 做什么：`schemas/clauses.v1.json`（Spec §3.1 的字段，含 `levels`、`applies`、`probe` 组合、`remedy`、`rationale`、`na_*`、`since`、`enforce_from`、`lifecycle`）；加载器；lint 检查 schema、id 唯一、档位引用有效、引用的探针存在。本任务只支持单份 `kind: base`。
  - 验收：一份玩具尺子（3 档、6 条）lint 通过；重复 id、引用不存在的档位、未知探针各报错，退出 2。
  - 依赖：T2、T3。文件：`schemas/clauses.v1.json`、`src/repo_readiness/clauses/`、`tests/test_clauses.py`、`tests/fixtures/rulesets/toy-base.json`。

- [x] **T5 打分函数**（S）
  - 做什么：纯函数：输入条款集 + 每条结果，输出档位、各档必须 / 建议计数、下一档差什么。规则来自尺子的 `gate`：必须全满足；建议项按尺子里的规则（`ratio` 向下取整，或 `max_missing` 每档最多缺 n 条，档位可单独覆盖）；逐档累进；N/A 过半判未达到；`unknown` 按不满足计但单列；豁免过期按不满足、不可豁免条款的豁免无效；`enforce_from` 之前按建议计；应用取最低。
  - 验收：表驱动测试覆盖上述每条规则，且每条都有一个"刚好差一点"的反例。
  - 依赖：T4。文件：`src/repo_readiness/detect/score.py`、`tests/test_score.py`。

- [x] **T6 纵向切片：`check` 端到端**（M）
  - 完成说明：退出码 0 / 1 / 2 已测；退出码 3（环境未就绪）在 T6 还没有能触发的场景，随 T9（GitHub 适配层：`gh` 未登录、网络不通）补测。
  - 做什么：探针运行时框架 + `fs` 探针（文件存在、glob、内容匹配）；`check` 子命令：加载尺子 → 跑探针 → 打分 → 写 `report.json`（`schemas/report.v1.json`）和 `summary.md`（≤ 30 行）；`--min-tier` 退出码 0 / 1 / 2 / 3。
  - 验收：玩具仓库 + 玩具尺子跑出期望档位；报告通过自身 schema；四种退出码各有用例；`</dev/null` 下不挂起。
  - 依赖：T5。文件：`src/repo_readiness/probes/{__init__,fs}.py`、`src/repo_readiness/report/`、`schemas/report.v1.json`、`tests/test_check_e2e.py`、`tests/fixtures/repos/toy/`。

- [x] **T7 接入结论 v1：`conclude` 与 `conclusion verify`**（S）
  - 做什么：`schemas/conclusion.v1.json`（Spec §3.3 + `default_branch` + `attestation` 占位）；`conclude` 只在报告完整（无待裁决、无探针错误）时出结论，否则退出 1 并说明缺什么；`valid_until` 默认签发 + 14 天；`verify` 核对报告 sha256。
  - 验收：玩具报告能出结论并通过 schema；报告改一个字节后 `verify` 失败；报告不完整时拒绝出结论。L0 结论也能出（未达标但报告完整）。
  - 依赖：T6。文件：`schemas/conclusion.v1.json`、`src/repo_readiness/conclusion/`、`tests/test_conclusion.py`。

### 检查点 A
- [ ] 全部测试通过，`/usr/bin/python3` 下也通过
- [ ] **三份格式（`clauses.v1`、`report.v1`、`conclusion.v1`）请用户过目**
- [ ] 用户过目后：条款格式发 `autopr-standard`（接口清单 #1）；结论 schema 发 `autopr-design`（#4）——发送前给用户看消息全文
- [ ] 经用户逐件同意：建远端 `haigeerlab/repo-readiness`、推送、打 `v0.1.0` tag，把 tag 与 SHA 告诉 `autopr-design`

## 阶段 2：基础档探针

- [x] **T8 v2.0 基础档试转写**（S）
  - 做什么：把 v2.0 基础档全部条款（G1–G7、V1、V2、D1、D2、E1、K1、R1、R2）写成 `clauses.v1`，作为测试夹具；标注"试转写，正式版归 `autopr-standard`"。
  - 验收：lint 通过；每条的强度、档位、适用、范围与标准原文逐条核对一致（核对表写进夹具旁的 README）。
  - 依赖：检查点 A。文件：`tests/fixtures/rulesets/autopr-onboarding-2.0-basic.trial.json`、同目录 `README.md`。

- [x] **T9 GitHub 平台适配层**（S）
  - 完成说明：顺带实现了 `github.repo`（G1，原属 T11）作为适配层的第一个使用者；`check` 遇到环境问题（gh 未登录、网络、限流、5xx、gh 缺失）退出 3，T6 欠的退出码 3 测试已补；真实录制夹具 `tests/fixtures/github/repo-readiness/`。
  - 做什么：`gh api` 只读封装（只允许 GET，其他方法直接拒绝）；录制 / 回放模式；识别 403 / 404 / 权限不足，转成"读不到"而不是"没有"。
  - 验收：非 GET 调用被拒；回放模式不联网；权限不足的返回被识别。
  - 依赖：T6。文件：`src/repo_readiness/platform/github.py`、`tests/test_github_adapter.py`。

- [x] **T10 G2 生效规则探针**（M）
  - 完成说明：三个真实仓库的结论与初评一致（pwa-platform met、agent-relay 只缺 PR、repo-readiness 三项都缺）。绕过名单的分类里有三处是我的保守取舍，待 `autopr-standard` 确认：Team 判阻断；仓库角色只有 admin（id 5）算管理员，其余角色判阻断；个人账号（User）算"存在绕过"而非阻断（agent 身份若是机器账号，这一条要改）。
  - 做什么：`github.effective_branch_rules`：旧版保护 ∪ 规则集逐项并集；只认 `enforcement: active`；bypass 名单：含 agent 身份或任何应用 / 集成判 `gap`，只有用户本人或管理员角色判 `met` 并标注「存在绕过」；读不到判 `unknown`。
  - 验收：四类真实返回录制成夹具——pwa-platform 规则集（`met`）、agent-relay 旧版保护未要求 PR（`gap`）、规则集 `evaluate`（`gap`，构造）、权限不足（`unknown`，构造）——结论全对。
  - 依赖：T9。文件：`src/repo_readiness/probes/github_rules.py`、`tests/test_probe_g2.py`、`tests/fixtures/github/`。

- [x] **T11 G1 / G4 / G5 / G6 设置类探针**（M）
  - 完成说明：G4 取 main 上最近一次已完成的 push / schedule / dispatch 运行（不算 PR，cancelled / skipped 不算结论），按 created_at 从检测时刻往回滚动 336 小时；G5 平台不报告时判 unknown 并提示需 CI 等效检查（该部分本版不判定）；G6 这里只做仓库设置部分，危险触发写法在 T12。待 `autopr-standard` 确认：G4 是否看"任一 workflow 的最近一次"（现做法）还是"每个 workflow 各自的最近一次"。
  - 做什么：仓库归属与默认分支（G1）；main 最近一次 CI 结论与日期（G4，从检测时刻往回滚动 336 小时）；秘密扫描与推送保护（G5，私有仓库读不到时判 `unknown` 并提示 CI 等效检查）；workflow 默认权限与"能否批准 PR"（G6 的设置部分）。
  - 验收：每个探针一正一反 + 一个读不到的夹具。
  - 依赖：T9。文件：`src/repo_readiness/probes/github_repo.py`、`tests/test_probe_repo.py`。

- [x] **T12 workflow 静态分析**（M）
  - 完成说明：先确认风险成立（5 个真实 workflow 有 3 个用多行块），经用户同意扩展 YAML 子集支持 `|` / `>`；实现 G3（`workflow.pr_runs_check`）、G6 触发部分（`workflow.no_dangerous_triggers`）、G9（`workflow.actions_pinned`），G9 在 5 个真实 workflow 上与初评一致。**G8 拆为 T12b**。注意：G3 要求 interface.yml 登记的 check 命令与 CI 的 run 步骤对得上（空白规范化后子串匹配，#21538），目前所有仓库都没有 interface.yml，G3 会判不满足，和初评的 ✅ 不同——T16 对照时按"新要求"说明。另外 agent-relay 的 CI 跑的是 `bash scripts/validate.sh`，它的 interface.yml 必须照此登记，写成 `/bin/bash …` 会对不上（T21 生成骨架时据此预填）。
- [ ] **T12b G8 必需检查无软失败**（M，标准档，不影响试点基础档）
  - 做什么：从 G2 已取到的旧版保护 `required_status_checks` 与规则集 `required_status_checks` 参数得到必需检查名单；把 workflow 的 job（含矩阵展开名 `name (…)`）对到名单；必需 job 上有 `continue-on-error: true` 判不满足；名单为空判不满足。"非必需任务软失败要写原因"靠注释，静态读不到，记为说明。
  - 依赖：T10、T12。
  - 做什么：解析 `.github/workflows/*.yml`（YAML 子集；超出子集的 workflow 判 `unknown` 并说明）：`pull_request` 触发且调用了 `interface.yml` 登记的 `check`（G3）；`pull_request_target`/`workflow_run` + checkout PR 代码的危险写法（G6）；必需任务上的 `continue-on-error`（G8）；`uses:` 是否 40 位 SHA（G9）。
  - 验收：每类写法正反夹具；agent-relay、pwa-platform 的真实 workflow 文件（只读拷贝）结论与初评一致。
  - 依赖：T2、T6。文件：`src/repo_readiness/probes/workflow.py`、`tests/test_probe_workflow.py`。
  - 风险：真实 workflow 可能超出 YAML 子集（多行 `run: |` 很常见）。**若超出，先停下报告**，再决定是扩子集还是只做行级扫描。

- [x] **T13 config / declare 探针**（M）
  - 完成说明：`config.parses`、`registry.owner_registered`（信箱名单用 `--registry FILE` 传入，工具不读 agent-relay 内部数据）、`risk.template_paths_kept`（类别模板用 `--risk-templates FILE` 传入，只识别完全相同的通配符）、`declare`；引擎按自评处理 N/A（na_allowed、理由与批准人）和豁免（理由、到期日、批准人；过期 / 超 90 天 / 不可豁免由打分判）；探针已满足时自评不覆盖。`check` 的类别与应用在未给参数时取自 readiness.yml。报告 v1 新增可选字段 `results[].waiver_until`（只加不改）。自评条目 v1 只认仓库级，按应用分别自评留待以后。`judge` 仍未实现（T17），先声明后裁决的条款在自评为"满足"时仍是"无法判定"。
  - 做什么：`config`（解析 YAML / JSON，按路径取值）；`declare`（读 `readiness.yml` 自评的 status / evidence / plan / reason / until / approved-by）；G7 三个登记文件存在且可解析；D1 指令文件提到 `check` 入口；R1 类别模板 T4 路径未被删（模板草案为夹具）。
  - 验收：缺文件、解析失败、自评格式错误、豁免超 90 天、G2 申请豁免（不允许）各有用例。
  - 依赖：T2、T6。文件：`src/repo_readiness/probes/{config,declare}.py`、`tests/test_probe_declare.py`。

### 里程碑 M1：agent-relay 第一份接入结论
- [ ] 用 T8 试转写 + T10–T13 只读检测 agent-relay，`check` → `conclude`（预计 L0）
- [ ] 结论与报告放在本仓库输出目录；**给用户看摘要后**发给 `autopr-design`。写进 agent-relay 仓库由用户和 `agent-relay-owner` 决定

- [ ] **T14 entry 探针**（M）
  - 做什么：按接口契约调用 `interface.yml` 的入口：临时 `git worktree` 检出被测 SHA、注入 `AUTOPR_*` 环境变量、超时、读报告或按退出码生成最小报告、跑后核对 git 状态未变、删除 worktree；仅在 `--exec-entries` 时执行，否则 `unknown`。覆盖 V1、V2。
  - 验收：玩具仓库的入口退出 0 / 1 / 2 / 3 / 超时 / 改动工作区六种情况结论正确；未开 `--exec-entries` 时一律 `unknown` 且列入 `not_evaluated`。
  - 依赖：T6。文件：`src/repo_readiness/probes/entry.py`、`tests/test_probe_entry.py`。

- [ ] **T15 生态适配器 + E1**（S）
  - 做什么：`adapters/*.json`（node、python、无依赖）；E1：有第三方依赖时锁文件入库且 CI 按锁文件安装；无第三方依赖时 N/A。
  - 验收：pwa-platform（`met`）、tier-guard 类无依赖仓库（`na`）、构造的"有依赖无锁文件"（`gap`）。
  - 依赖：T12。文件：`src/repo_readiness/adapters/`、`src/repo_readiness/probes/ecosystem.py`、`tests/test_probe_e1.py`。

- [ ] **T16 标准答案对照**（S）
  - 做什么：`tests/golden/run_golden.py`（不进默认测试，要联网，只读）：对 12 个仓库跑 T8 尺子，把自动条款结论和 `assessment-v2.md` 的总表对比，生成 `docs/golden/2026-11-xx-golden.md`。
  - 验收：每个差异都有原因（工具错 → 修；初评错或时点不同 → 写明）。
  - 依赖：T10–T15。文件：`tests/golden/`、`docs/golden/`。

### 检查点 B
- [ ] 全部测试通过；对照报告用户过目

## 阶段 3：裁决、复检、组合

- [ ] **T17 裁决交接**（M）：`judgment-requests.json` / `judgments.json` 两份 schema；证据指纹；指纹不变沿用上次结论；校验裁决引用的文件存在、行号在范围内、只裁决被请求的条款。验收：伪造引用、越权裁决、指纹变化三类用例。依赖：T6。
- [ ] **T18 复检 `diff` + 掉档信号**（M）：条款文件 v1 加可选顶层块 `drop: {consecutive_failures: 2, immediate: [ids]}`（用户 2026-11-20 定，#21609 已告知 autopr-standard；不写时默认 2 次、无立即掉档）；状态 / 档位 / 证据变化；原因类别（仓库、尺子、豁免过期、声明过期、权限或环境）；报告记录必须自动条款的连续不满足次数；`drop_signals[]`（连续两次，或 G2 / G5 / G6 一次）。验收：尺子换版本不误报退步；两次 / 一次触发规则各有正反用例。依赖：T7、T17。
- [ ] **T19 尺子组合**（M）：`kind: stack`、`detect`、`tighten`；仓库 `stacks`（含按应用）；声明优先、不一致进"待确认"；放宽 / 重复定义 / 改适用范围加载失败。验收：玩具技术栈尺子不改代码能加；四类违规各报错。依赖：T4、T5。

### 检查点 C
- [ ] 全部测试通过；用户过目

## 阶段 4：修复与入口

- [ ] **T20 修复框架 + 精确命令**（M）：`remedy` 子命令；三类输出（patch + PR 草稿 / 精确命令 + 预期 + 撤回方法 / 建议 + 参考）；G2 生成 `gh api` 写命令（只打印不执行）；D1 给出指令文件要加的段落。依赖：T13、T18。
- [ ] **T21 G7 登记文件补丁**（M）：按探到的事实预填 `readiness.yml`、`interface.yml`、`risk-tiers.yml`（`extends` 类别模板草案）骨架，输出 `.patch`。验收：对 agent-relay 的只读副本 `git apply --check` 通过；应用后（临时副本）复检 G7 `met`。依赖：T20。
- [ ] **T22 skill**（S）：`skills/repo-readiness/SKILL.md`，Claude Code / Codex 共用；流程：扫描 → 裁决 → 打分 → 讲摘要 → 逐项问确认 → 复检。依赖：T17、T20。

### 检查点 D
- [ ] 修复产物用户过目

## 阶段 5：试点

- [ ] **T23 agent-relay 闭环**：检测 → 补丁与命令 → **每一项落地都单独征得用户同意**（G2 分支保护、D1 指令文件、G7 登记文件由 `agent-relay-owner` 合并）→ 复检 → 结论（目标基础档）。
- [ ] **T24 切片 1 联调**：结论提交到 agent-relay 后，切片 1 的 `autopr/admission` 显示 L2，sha256 对得上（第一阶段验收线）。依赖：`autopr-design` 的中心仓库与 workflow。
