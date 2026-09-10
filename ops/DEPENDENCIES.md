# 自托管镜像与许可

镜像使用不可变 digest；升级时须同时更新本表、构建并重跑恢复演练。

| 组件 | 固定版本 | 许可 |
| --- | --- | --- |
| PostgreSQL | `postgres:17@sha256:67f41722…` | PostgreSQL License |
| Mailpit | `axllent/mailpit@sha256:7f33095f…` | MIT |
| Bun（构建阶段） | `oven/bun:1.3.4@sha256:7608db4a…` | MIT |
| uv（构建阶段） | `ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58…` | MIT / Apache-2.0 |
| Python | `python:3.14.3-slim-bookworm@sha256:f21c0d5a…` | PSF-2.0；基础系统组件遵循 Debian 各软件包许可 |

应用自身使用仓库根目录 [LICENSE](../LICENSE) 的 MIT 许可。完整 digest 以 `compose.yml`、`ops/compose.yml` 与 `Dockerfile` 为准。
