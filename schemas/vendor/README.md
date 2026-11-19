# 外部 schema

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `entry-report.v1.json` | `autopr-standard` 接口层契约草案的 `entry-report.schema.json`（2026-11-19，sha256 ff5b9539…） | 被测仓库入口写出的报告格式（`autopr.entry-report/v1`）。`entry.run` 探针用它校验 `report: native` 的入口报告。内容归 `autopr-standard`，这里是原样拷贝，对方更新后同步替换 |
