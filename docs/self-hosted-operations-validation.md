# 自托管、留存与恢复演练（#33）

本记录是 2026-09-10 在专用 `bp-issue-33` 本地资源上的软件与运维证据，不是公网部署、真实邮件送达、外部备份或生产容量承诺。可复现命令见 [ops/README.md](../ops/README.md)。

## 环境和全栈结果

- macOS 26.5.2 arm64，Docker Engine 29.6.2，Compose v5.3.1；主机验证使用 Python 3.14.5 / uv 0.11.14，容器运行 Python 3.14.3 固定镜像。
- 固定 digest 的 PostgreSQL 17、Mailpit、Bun、uv 与 Python 镜像成功构建 100,949,661 字节应用镜像；许可清单见 [ops/DEPENDENCIES.md](../ops/DEPENDENCIES.md)。
- `app`、唯一生产 `worker`、PostgreSQL、Mailpit 均健康。API `18138` 和 HTTPS `18443` 均以本地证书访问 `/health` 返回 200；服务只绑定 `127.0.0.1`。
- 数据库、应用和 worker 实际重启后，管理员记录数量、独立删除日志身份/序号、ready 状态、受控缓存文件均保持。显式 `stop worker` 后仅重启数据库没有拉起 worker；随后显式 `up worker` 才恢复，停止意图没有被基础服务重启绕过。
- `python3 ops/backup.py` 实际承接 Compose `pg_dump -Fc`，待命令成功并经同一固定 PostgreSQL 镜像 `pg_restore --list` 验证后，才由 operator 登记为 0600 本地 dump（3,614,643 字节）。临时文件已清除；数据库 dump 与 `.private/runtime.env` / 独立 SQLite 注销日志分开，没有创建外部目的地。

## 恢复、删除与密钥演练

`uv run --directory backend python tests/operations_restore.py` 创建唯一基目录 `/tmp/bp-issue-33-95jpnsyv`、两个独立合成数据库和 270,180 字节真实 dump，完整通过：

1. 备份前保存 v1 AES-GCM 密文、七类未完成业务状态、已完成成果、确定 token 用量和未知用量；dump 由实际 PostgreSQL 17 `pg_dump` 生成并通过生产 operator 登记。
2. 在线库将全部配置事务性轮换到 v2，移除 v1 材料后仍能解密；旧 v1 dump 保持不变。备份后向数据库外的 SQLite 追加合成账号注销事实。
3. 在运行 `pg_restore` 前先原子发布 `restoring`，此时直接启动真实 API、worker、普通 check 及 `version=None` 编辑态探针均非零退出；证明门禁生效后才把 dump 恢复到隔离数据库。损坏状态下 finish 非零退出且未开放，恢复状态后同一流程可安全重试。
4. 可信 `finish-restore` 先重放注销事实并清除目标账号，再撤销恢复出的全部 ModelConfig，终止 training/project/topic/submission/evaluation/review/concept 七类未完成状态（覆盖 `needs_supplement`、`needs_clarification`），取消 7 个旧队列任务，最后原子发布 ready。
5. 已完成 Candidate、调用次数与 7 token 用量逐字段保留；未知用量没有补零。ready 后普通 check 可重复通过，不误进恢复流程。

缺失、损坏或身份/序号落后的独立状态继续返回失败；CLI 只输出泛化错误，不打印 SQL、Key 或恢复出的正文。恢复必须由操作者先停止 app/worker；API 无绕过参数。

## 留存、安全与容量边界

12 项运维/注销日志测试验证 UID/GID 0 在写文件前被拒，`pg_dump` 或格式验证失败不调用登记且不留临时文件；7 天边界只删除专属无引用普通文件，符号链接和未知备份文件失败关闭；30 天边界删除已登记 dump；活跃草稿不随缺席时间清除。日志文件为 0600，只包含 UTC 时间与级别，受控 Key、密码、提示词、异常和学习原文均未出现。

`python3 ops/measure.py` 用唯一基目录 `/tmp/bp-issue-33-measure-s861ezzd` 实际复跑并保存原始日志。项目解析与文件边界 30 项通过（1.29 秒测试时间，1.85 秒墙钟）：最多 48 次请求、2 MiB 单响应、1 MiB blob、3000 目录项、16 段、每段 24 KiB；覆盖大文件续读、指定行、二进制/符号链接/恶意脚本只解析不执行、路径/ref/限流/TLS/跳转/压缩及失败出口。这是输入资源边界，不是累计模型 token 或任务限额。

本机实际 HTTPS 测量如下；样本小，只用于发现数量级与失败出口，不外推生产 SLA：

| 操作 | 样本 | 中位 | p95 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| 页面读取 | 20 | 10.23 ms | 19.19 ms | 47.82 ms |
| 8 并发健康读取 | 32 | 18.49 ms | 30.14 ms | 30.68 ms |
| 登录会话事务保存 | 3 | 51.16 ms | 55.52 ms | 55.52 ms |

同一脚本在负载结束后采样 app/worker/db/mail 分别为 118.2/102.9/99.58/12.13 MiB，瞬时 CPU 为 0.23%/0.92%/0.31%/0.00%；一次采样只反映本机当时状态。端口预检在全栈运行时准确列出 16392、11505、18405、18138、18443 冲突并以退出码 1 结束，不停止占用端口的服务。

所有样本为合成数据。没有运行目标仓库脚本、安装目标仓库依赖、调用真实模型、使用真实 API Key、发送公网邮件、购买服务、部署公网或清理演练数据库/产物。
