# GitHub 录制夹具

由 `repo-readiness check --github-record <目录>` 只读录制（仅 `gh api --method GET`）。每个文件是一次请求的状态、HTTP 码、正文与限流相关响应头，按请求路径的 sha256 前 16 位命名。

| 目录 | 录制时间 | 内容 |
| --- | --- | --- |
| `repo-readiness/` | 2026-11-19 | `repos/haigeerlab/repo-readiness`（G1） |
