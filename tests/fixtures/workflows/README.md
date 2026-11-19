# workflow 夹具

2026-11-20 从本机检出原样复制的 5 个公开仓库的 CI workflow，用于 YAML 子集解析与 workflow 静态分析（G3、G6、G8、G9）。

| 文件 | 来源提交 |
| --- | --- |
| pwa-platform.ci.yml | 3f927d0 |
| agent-relay.ci.yml | 1e25cc6 |
| spec-guard-plugin.ci.yml | 01420620 |
| tab-leader.ci.yml | 160abde |
| sso-browser-sdk.ci.yml | cf7bb42 |

其中 agent-relay、tab-leader、sso-browser-sdk 用了多行块（`run: |`），是扩展 YAML 子集的直接原因。
