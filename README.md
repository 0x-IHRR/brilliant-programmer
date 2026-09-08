# 我是天才程序员

当前交付：[T01 #2](https://github.com/0x-IHRR/brilliant-programmer/issues/2) 本地邀请注册。尚未部署，尚未开放受邀试用；邮件验证及训练业务是后续任务。

## 运行

需要 Docker、uv、Bun。命令在仓库根目录执行；仅创建专用本地数据库，不访问其他容器。

```sh
python3 scripts/init_local.py
# 本机查看 .env 中的管理员邮箱/随机密码；已有 .env 时脚本拒绝覆盖。
docker compose -p bp-issue-2 up -d --wait
uv sync --all-packages --locked
uv run --directory backend alembic upgrade head
uv run --directory backend python -m app.initial_data
bun install --frozen-lockfile
bun run --cwd frontend build
uv run --directory backend uvicorn app.main:app --host 127.0.0.1 --port 18080 --no-proxy-headers
```

打开 http://127.0.0.1:18080 。管理员用 `.env` 中的凭据登录，生成、复制并自行分发邀请码；注册者自设 12–128 字符密码。管理员初始化仅在账号不存在时运行，不覆盖既有账号或密码。不要把真实邮箱密码填入本地测试配置。

前端开发：`bun run --cwd frontend dev`，地址 http://127.0.0.1:18173 ，代理到本机 18080。PostgreSQL 端口可由 `.env` 的 `DB_PORT` 调整，同时修改 `DATABASE_URL`；Compose project 名可另选以隔离并行任务。当前 Compose 只提供数据库，本票在宿主机运行应用。生产 Compose、TLS、邮件等不在本票上线承诺内。

## 验证与生成客户端

```sh
uv run --directory backend pytest tests -q
uv run --directory backend ruff check app tests
uv run --directory backend mypy app
uv run --directory backend python -c 'import json; from app.main import app; print(json.dumps(app.openapi()))' > frontend/openapi.json
bun run --cwd frontend generate-client
bun run --cwd frontend build
# 保持上面的 API 运行；首次缺少浏览器时执行 bunx --cwd frontend playwright install chromium
bun run --cwd frontend test
```

测试需要迁移后的真实 PostgreSQL；请使用专用本地测试数据库。测试添加随机合成账号/邀请，不清空数据库、不使用真实个人数据。API 测试每次使用唯一模拟客户端标识，仍执行限速，避免重复运行被上一轮窗口干扰。浏览器测试操作真实页面、剪贴板和数据库。截图保存到被 Git 忽略的 `frontend/test-results/invitation-account.png`。

## 账号契约与边界

- `POST /api/v1/users/signup`：邮箱、用户密码、邀请码。邮箱统一小写；不可由请求设置管理员、等级或验证状态。初始为小白程序员、邮箱未验证。
- `POST /api/v1/login/access-token` 与 `GET /api/v1/users/me`：模板 Argon2 密码校验和 JWT 登录（1 小时）；当前设备退出清除 sessionStorage。密码重置及全设备失效由 T03 实现。
- `GET /api/v1/training/access` 使用共享 `get_training_user`，未验证邮箱返回 403。后续所有训练路由必须复用该依赖；此接口只检查准入，不声称训练业务存在。
- 管理员独占 `POST/GET /api/v1/invitations` 和 `POST /api/v1/invitations/{id}/revoke`；列表每页 100 个，可刷新/翻页查询真实状态，不暴露注册人资料。邀请码是 256 位随机持有凭证，产品仅向管理员返回；不自动过期、不绑定收件人。
- 注册及作废锁定同一邀请行；账号 INSERT 与 `used` 在同一 PostgreSQL 事务提交。重复邮箱或插入失败回滚，不耗码；并发只能注册或作废一方生效。已用码不可恢复。重复作废幂等。浏览器未收到响应时先登录已有账号或由管理员刷新状态，不因超时恢复邀请码。
- 服务端未挂载模板的公开无邀请注册、私有测试用户创建、管理员用户列表/修改/删除、改邮箱、密码邮件、找回密码或第三方登录接口。
- 登录/注册按连接客户端地址与路径分别限制每分钟 60 次，计数由 PostgreSQL 原子更新，过期记录清理。只存 HMAC 地址摘要；本地服务不信任代理头。生产使用前需设计可信代理及运营限速，不将本机规则称为完整生产防护。
- 本地无邮件、短信、分析上报或模型调用。邀请数据库和 `.env` 需按秘密保护；操作者技术访问不等同产品管理员权限。

## 上游与许可

固定官方 [Full Stack FastAPI Template 0.12.0](https://github.com/fastapi/full-stack-fastapi-template/tree/84c5a9e11a9e58262599e3d772f5386924e02ca7)，commit `84c5a9e11a9e58262599e3d772f5386924e02ca7`，MIT，原 [LICENSE](LICENSE) 保留。

复用并适配上游 FastAPI/SQLModel/Argon2/JWT 账号基础、Alembic、React/Vite/shadcn 原生组件、OpenAPI SDK 生成与 pytest/Playwright 基础；去掉演示 Items、扩权用户管理、密码邮件、遥测和不适用部署文件。没有引入第二套 UI 或服务体系。依赖具体版本由 `uv.lock` 与 `bun.lock` 固定；上游依赖各自许可仍适用。
