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

## 状态

开发中（T1 项目骨架）。命令按 [tasks/todo.md](tasks/todo.md) 的顺序陆续加入。
