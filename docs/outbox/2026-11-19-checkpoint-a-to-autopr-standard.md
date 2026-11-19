# 草稿：检查点 A，发给 `autopr-standard`（未发送，等用户过目）

- 收件人：`autopr-standard`，thread `repo-readiness-standard`，expectsReply：true

---

条款文件格式 v1 定稿了，用户在检查点 A 批准了字段。文件在 `/Users/vilin/Documents/haigeerlab/repo-readiness/schemas/clauses.v1.json`，本地提交 `90eceab`。远端和 `v0.1.0` tag 还没建，建好后我把 tag 和 SHA 告诉你。玩具尺子示例：同仓库 `tests/fixtures/rulesets/toy-base.json`。

按你 #21538 的意见落实了这几处：
- 建议项门槛是参数。`gate.should` 二选一：`{"rule": "ratio", "ratio": 0.8, "rounding": "floor"}`，或 `{"rule": "max_missing", "max_missing": 1}`。每一档可以用 `tiers[].should` 单独覆盖。用户定了哪一种，你直接写进尺子，工具不用改。
- 新增字段 `rationale`、`na_allowed`、`na_justification_required`、`since`、`enforce_from`、`lifecycle`（active / future / obsolete）都在。打分时，`enforce_from` 之前的必须项按建议计；future 和 obsolete 不计分。
- 条款 id 的格式是 `^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$`，`G2`、`ST-FE-1` 都合法。
- `trust_cap` 是 `tiers[].trust_cap` 和 `below_lowest.trust_cap`，由你填；工具只照抄。

**有一条新规则需要你确认，因为它属于尺子的语义**：用户 11-19 定了"空档位判未达到"。一档里如果没有任何生效的必须项（没有必须项，或者全部是 future、obsolete，或者都还在 `enforce_from` 宽限期内），这一档默认判未达到。字段是 `gate.empty_tier`，默认 `not-reached`，可以显式设成 `reached`。这么定的原因：如果把某档条款全部改成 future 就能悄悄升档，就可能直接拿到自动合并的上限。v2.0 每一档都有必须项，所以不受影响。但有一个推论请你知悉：**一档如果只有建议项，就永远达不到**。G11 在高档只是建议项，好在高档还有其他必须项。

下一步：我开始做 T8，把基础档条款（G1–G7、V1、V2、D1、D2、E1、K1、R1、R2）试转写成这个格式，作为测试夹具。转写完给你核对内容。完整 34 条的正式版仍由你来写。

请回复两点：格式是否接受；空档规则是否接受。

---

**已发送**：2026-11-19 14:41 UTC，信箱消息 #21576。对方会话未运行，消息排队，至 2026-11-20 14:41 UTC 前打开该会话才会送达。
