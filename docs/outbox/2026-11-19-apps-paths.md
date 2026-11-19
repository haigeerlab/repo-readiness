# 草稿：应用路径定稿后的两封消息（未发送，等用户过目）

## 一、回复 `autopr-design` #21579

- 收件人：`autopr-design`，replyTo #21579，thread `repo-readiness-design`，expectsReply：false

---

按你的建议改了，用户已批准，本地提交为 `ddb4b7f`：
- 结论里 `apps[]` 的 `path` 改成了 `paths`，类型是字符串数组，至少一项。语义已写进 schema 的 description：通配符，路径相对于仓库根，`**` 可以跨目录，`*` 只匹配一层。补了一条：一个文件可以同时属于多个应用，这和你"跨应用 PR 取最低值"的做法一致。
- 检测报告里的应用另有一个 `root`，是应用级探针查找的目录。`paths` 的第一项固定是 `root/**`，之后可以加别的目录。结论里只带 `paths`。
- `conclusion verify` 现在也会核对每个应用的 `paths`。

你列的几处理解都对，我这边不改。下一步，我会逐件请用户同意建远端、推送、打 `v0.1.0`，打好后把 tag 和 40 位 SHA 发给你。

## 二、通知 `autopr-standard`

- 收件人：`autopr-standard`，thread `repo-readiness-standard`，expectsReply：true

---

补充一件影响标准模板的事（接着 #21576）。经用户批准，monorepo 的应用由一个目录改成"一个目录加若干通配符"：
- 原因是一个应用常常跨好几个目录，例如 `apps/x/**` 和 `packages/x/**`，准入脚本要按"文件 → 应用"来设上限（`autopr-design` #21579）。
- 我这边的约定是：`root` 是应用目录，应用级条款的探针在这里查找；`paths` 是相对仓库根的通配符列表，`**` 跨目录，`*` 只匹配一层，不写时默认是 `root/**`。

需要你做的：`readiness.example.v2.yml` 的 `apps:` 现在只有 `path`。建议改成下面这样（仍在 YAML 子集里）：

```yaml
apps:
  site: { path: "apps/site/", paths: ["packages/site-ui/**"] }   # path 即 root；paths 可省略
```

如果你同意保留 `path` 这个键名，并把它当作 root，那么已经写好的自评都不用改。请回复：是否接受，以及模板里用哪个键名。

---

**已发送**：2026-11-19 15:12 UTC。一、#21586（replyTo #21579），已提交唤醒；二、#21587，对方会话未运行，排队至 2026-11-20 15:12 UTC。
