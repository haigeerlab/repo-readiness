# GitHub 录制夹具

由 `repo-readiness check --github-record <目录>` 只读录制（仅 `gh api --method GET`）。每个文件是一次请求的状态、HTTP 码、正文与限流相关响应头，按请求路径的 sha256 前 16 位命名。

| 目录 | 录制时间 | 内容 |
| --- | --- | --- |
| `repo-readiness/` | 2026-11-19 | `repos/haigeerlab/repo-readiness`（G1）；main 的旧版保护（未设置）、生效规则（无）（G2） |
| `pwa-platform/` | 2026-11-19 | main 的旧版保护（未设置）、生效规则、规则集 23986228「main: PR and CI gate」（G2：规则集保护，v1.0 初评误判过的场景） |
| `agent-relay/` | 2026-11-19 | main 的旧版保护（禁 force push、禁删除，未要求 PR）、生效规则（无）（G2） |

构造的夹具（规则集处于 evaluate / disabled、权限不足、绕过名单含应用等）不落盘，由 `tests/test_probe_g2.py` 在这些真实录制上改一个字段生成。
