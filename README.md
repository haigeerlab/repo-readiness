# repo-readiness

用一把"尺子"（条款文件）检测代码仓库的就绪度：报告在哪一档、差什么、怎么补；补完复检，达标后出一份接入结论，交给 Auto PR 作为接入依据。

- 设计：[docs/spec/SPEC.md](docs/spec/SPEC.md)（已批准）、[ASSUMPTIONS](docs/spec/ASSUMPTIONS.md)
- 计划：[tasks/plan.md](tasks/plan.md)、[tasks/todo.md](tasks/todo.md)

## 运行

只需要 python3（≥ 3.9，macOS 自带的 `/usr/bin/python3` 即可），零第三方依赖。

```bash
bin/repo-readiness --version
```

## 开发

```bash
bin/validate.sh
```

会先用当前的 `python3` 跑全部测试，再用 `/usr/bin/python3`（3.9）跑一遍。

## 命令

```bash
bin/repo-readiness clauses lint RULER.json [--base BASE.json]        # 校验尺子（技术栈尺子要带 --base）
bin/repo-readiness check REPO --clauses RULER.json --out OUT \
    [--stack-clauses STACK.json ...] [--repo-name owner/name] [--min-tier basic] \
    [--baseline OLD/report.json] [--judgments judgments.json] [--exec-entries] \
    [--registry agents.json] [--risk-templates templates.yml]
bin/repo-readiness diff OLD/report.json NEW/report.json [--json diff.json]   # 有掉档信号时退出 1
bin/repo-readiness conclude OUT/report.json --default-branch main --out conclusion.json
bin/repo-readiness conclusion verify conclusion.json --report OUT/report.json
```

退出码：0 通过 / 达到目标档，1 未达到 / 有掉档信号 / 拒签，2 用法或尺子错误，3 环境未就绪（如 gh 未登录、网络、入口超时）。

## 状态

`v0.3.0`：基础档探针、裁决交接、复检与掉档信号、尺子组合已完成；修复（T20–T22）与试点（T23–T24）进行中，见 [tasks/todo.md](tasks/todo.md)。
