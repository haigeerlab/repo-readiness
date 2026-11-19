# 生态适配器

E1（有第三方依赖时依赖锁定、CI 按锁定版本安装）用到的各生态知识，全部写在这里的 JSON 里；工具核心不认识任何语言工具。

| 字段 | 含义 |
| --- | --- |
| `manifests` | 依赖清单文件名，在仓库（或应用目录）里所有被 git 跟踪的文件中查找，不只看根目录 |
| `dependency_parser` | 判断清单里有没有第三方依赖的解析器（`package_json`、`python`），代码在 `probes/ecosystem.py` |
| `lockfiles` | 锁文件名；在清单所在目录或任一上级目录（不超出应用目录）找到即可 |
| `pinned_requirements` | `requirements*.txt` 全部按 `==` 固定（或带 `--hash`）也算锁文件 |
| `frozen_commands` | CI 的 run 步骤里出现即算"按锁定版本安装"（空白规范化后子串匹配） |
| `frozen_actions` | CI 里以这些 action 安装且参数匹配，也算 |
| `install_commands`、`install_actions` | 任何安装这个生态依赖的写法。CI 有安装、但都不是按锁定版本 → 不满足；CI 有 workflow、但根本不装这个生态 → 只要锁文件在就满足（并注明）；完全没有 CI → 同样只看锁文件（CI 是否存在由 G3 判） |

加一个生态 = 加一个 JSON（必要时加一个解析器），不改判定逻辑。
