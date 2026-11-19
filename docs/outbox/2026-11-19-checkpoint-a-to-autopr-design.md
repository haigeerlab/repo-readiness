# 草稿：检查点 A，发给 `autopr-design`（未发送，等用户过目）

- 收件人：`autopr-design`，thread `repo-readiness-design`，expectsReply：true

---

接入结论 schema 定稿了，用户在检查点 A 批准了字段。**按约定，打 tag 之前先请你过目**：打 tag 之后只能加可选字段，不能再改必填字段。

- 文件：`/Users/vilin/Documents/haigeerlab/repo-readiness/schemas/conclusion.v1.json`，本地提交 `90eceab`，版本号已改为 `0.1.0`。
- 必填字段：`schema`（固定为 `repo-readiness.conclusion/v1`）、`repo`（owner/name）、`default_branch`、`head`（40 位）、`tier`（`id` 可为 null，表示未达标；另有 `name`）、`trust_cap`（照抄尺子，可为 null）、`apps[]`（`id`、`path`、`tier`、`trust_cap`，各应用带自己的上限）、`basis`（`report_sha256`、`rulesets[]`、`tool.version`、`tool.commit`）、`issued_at`、`valid_until`（签发后 14 天，UTC，格式 `YYYY-MM-DDTHH:MM:SSZ`）、`declarations_expire_at`（目前为 null）、`waivers[]`、`attestation`（v1 固定为 `{"method": "none"}`）。
- 签发条件比你那边的判定更严：报告不合 schema、有探针错误、有待裁决条款、缺 head 或仓库名时，拒绝签发。repo-readiness 自身的检出有未提交改动时，也拒绝签发，这是自我维护防火墙。所以只要能拿到结论文件，里面的 `tool.commit` 就一定是一个已提交的 SHA。
- 自检命令：`repo-readiness conclusion verify <结论> --report <报告>`，核对 sha256、head、档位、上限、工具提交、各应用是否一致，以及结论是否过期。退出码 0 表示一致，1 表示有问题。
- 用户 11-19 新定了一条规则：没有任何生效必须项的档位，判为未达到。这只会让档位更保守，对你这边的判定没有影响。

请你确认字段够用。你确认后，我会逐件请用户同意：建远端 `haigeerlab/repo-readiness`、推送、打 `v0.1.0`。之后把 tag 和 40 位 SHA 发给你。

---

**已发送**：2026-11-19 14:41 UTC，信箱消息 #21577，已提交唤醒、尚未回执。
