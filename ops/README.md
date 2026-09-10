# 本地自托管运行与恢复

仅在本机回环地址提供服务。以下命令从仓库根目录执行；`bp-issue-33` 是隔离的 Compose project，不会停止其他服务。

```sh
python3 ops/prepare.py ports
python3 ops/prepare.py prepare
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml up -d db mail
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml build app worker operator
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm --entrypoint alembic operator upgrade head
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm operator initialize
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml up -d app worker
curl --cacert .private/tls/cert.pem https://localhost:18443/health
```

API 诊断端口 `18138` 与 HTTPS 入口 `18443` 都使用相同 TLS，不提供明文 HTTP。应用、worker 与数据库均有健康检查；`.private/state` 和 PostgreSQL named volume 持久化。普通 `restart app worker` 只重启进程，不进入恢复流程。
`prepare` 将容器进程 UID/GID 绑定为当前主机用户，使 Linux 上的 0600 密钥和 0700 状态目录仍可访问；应用进程保持非 root。
若当前主机 UID 或 GID 为 0，`prepare` 会在创建任何文件前拒绝运行；不得手写 `APP_UID=0` 或 `APP_GID=0` 绕过此约束。

## 备份、轮换与留存

每天由主机调度下列一条命令。`pg_dump` 由固定 PostgreSQL 镜像执行，先用 `pg_restore --list` 验证；operator 在跨进程状态锁内 fsync 唯一 partial、提交 SQLite 登记，再原子 rename。commit 前中断的未登记 partial 满 1 天清理，commit 后 rename 前中断由下次存储或留存入口恢复；未知 final 继续失败关闭。独立删除日志从不进入 PostgreSQL dump。

```sh
python3 ops/backup.py
```

worker 每分钟清理专属 `unreferenced-cache` 中满 7 天的普通文件、满 30 天的脱敏日志和已登记 dump，并检查注销在 24 小时内完成。活跃账号草稿、题目、成果与正式记录不按最后访问时间清除。日志只写 UTC 时间和级别，不序列化消息、参数、异常、Key、密码、提示词或学习原文。

轮换时先把旧、新两版材料同时放入 `.private/runtime.env`，将 `MODEL_ACTIVE_KEY_VERSION` 指向新版，再执行：

```sh
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml stop app worker
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm operator rotate-keys
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml up -d app worker
```

确认所有密文已是新版后才能从环境和离线恢复清单移除旧材料。密钥环境文件与数据库 dump 分开保存。

## 旧备份恢复

恢复会替换当前产品数据库，先核对 dump UUID 和目标 Compose project。应用与 worker 必须保持停止；若任何命令中断，保持 `restoring`，从恢复数据库步骤安全重试。

```sh
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml stop app worker
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm operator isolate
# 以下三个命令必须全部非零退出，才能开始替换数据库。
! docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm operator check
! docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm --entrypoint python operator -m app.operations.runtime api
! docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm --entrypoint python operator -m app.operations.runtime worker
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml exec -T db dropdb -U bp --force bp
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml exec -T db createdb -U bp bp
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml exec -T db pg_restore -U bp -d bp --no-owner --exit-on-error < .private/state/backups/BACKUP_UUID.dump
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm --entrypoint alembic operator upgrade head
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml run --rm operator finish-restore
docker compose -p bp-issue-33 --env-file .private/runtime.env -f compose.yml -f ops/compose.yml up -d app worker
```

`finish-restore` 只能由隔离中的本地 CLI 绕过 ready 门：先重放独立注销日志，再撤销恢复出的全部模型配置，终止七类未完成任务（包括待补充、待澄清）并取消旧队列任务，最后原子发布 `ready`。缺失或损坏的状态、删除日志及身份/序号冲突均保持关闭。已完成成果、调用次数和已知/未知用量不被重写。

公网主机、域名、真实 SMTP、外部备份目的地和付费部署不在本地配置范围内。

## 可复现测量

全栈健康时运行下列命令。脚本用唯一 `/tmp/bp-issue-33-measure-*` 基目录保存 30 项解析/文件/失败边界日志，随后测量 HTTPS 页面、8 并发健康请求、三次登录保存、四容器 CPU/内存，并证明全栈占用时专用端口预检非零退出。输出只含汇总和产物路径，不含运行密钥。

```sh
python3 ops/measure.py
```
