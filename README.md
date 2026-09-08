# 我是天才程序员

当前交付：[T01 #2](https://github.com/0x-IHRR/brilliant-programmer/issues/2) 邀请注册和 [T02 #3](https://github.com/0x-IHRR/brilliant-programmer/issues/3) 邮箱验证与登录退出。尚未部署，尚未开放受邀试用；训练业务由后续任务实现。

## 运行

需要 Docker、uv、Bun。命令在仓库根目录执行；仅创建专用本地数据库，不访问其他容器。

```sh
python3 scripts/init_local.py
# 本机查看 .env 中的管理员邮箱/随机密码；已有 .env 时脚本拒绝覆盖。
docker compose -p bp-local up -d --wait
uv sync --all-packages --locked
uv run --directory backend alembic upgrade head
uv run --directory backend python -m app.initial_data
bun install --frozen-lockfile
bun run --cwd frontend build
uv run --directory backend uvicorn app.main:app --host 127.0.0.1 --port 18080 --no-proxy-headers
```

打开 http://127.0.0.1:18080 。管理员用 `.env` 中的凭据登录，生成、复制并自行分发邀请码；注册者自设 12–128 字符密码。管理员初始化仅在账号不存在时运行，不覆盖既有账号或密码。不要把真实邮箱密码填入本地测试配置。

前端开发：`bun run --cwd frontend dev`，地址 http://127.0.0.1:18173 ，代理到本机 18080。PostgreSQL 端口可由 `.env` 的 `DB_PORT` 调整，同时修改 `DATABASE_URL`；Compose project 名可另选以隔离并行任务。当前 Compose 提供数据库和仅本机访问的 Mailpit 测试收件端，本票在宿主机运行应用。生产 Compose、TLS 与真实邮件服务兼容性尚未验收。Mailpit 收件页面默认 http://127.0.0.1:18025 ，SMTP 端口 11025；不会向真实收件人投递。

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
- `POST /api/v1/login/access-token` 与 `GET /api/v1/users/me`：Argon2 密码校验、JWT 登录（1 小时）及数据库会话归属/过期检查；`POST /api/v1/login/logout` 删除当前会话，随后页面清除 sessionStorage，旧令牌即时不能发起新请求，其他设备仍可用。在途请求不保证撤销。升级前不含会话 ID 的旧 JWT 需重新登录。密码重置及全设备失效由 T03 实现。
- `GET /api/v1/training/access` 使用共享 `get_training_user`，未验证邮箱返回 403。后续所有训练路由必须复用该依赖；此接口只检查准入，不声称训练业务存在。
- 管理员独占 `POST/GET /api/v1/invitations` 和 `POST /api/v1/invitations/{id}/revoke`；列表每页 100 个，可刷新/翻页查询真实状态，不暴露注册人资料。邀请码是 256 位随机持有凭证，产品仅向管理员返回；不自动过期、不绑定收件人。
- 注册及作废锁定同一邀请行；账号 INSERT 与 `used` 在同一 PostgreSQL 事务提交。重复邮箱或插入失败回滚，不耗码；并发只能注册或作废一方生效。已用码不可恢复。重复作废幂等。浏览器未收到响应时先登录已有账号或由管理员刷新状态，不因超时恢复邀请码。
- 服务端未挂载模板的公开无邀请注册、私有测试用户创建、管理员用户列表/修改/删除、改邮箱、密码邮件、找回密码或第三方登录接口。
- 登录/注册按连接客户端地址与路径分别限制每分钟 60 次，计数由 PostgreSQL 原子更新，过期记录清理。只存 HMAC 地址摘要；本地服务不信任代理头。生产使用前需设计可信代理及运营限速，不将本机规则称为完整生产防护。
- 本地邮件仅交付受控 Mailpit，无真实邮件、短信、分析上报或模型调用。邀请数据库和 `.env` 需按秘密保护；操作者技术访问不等同产品管理员权限。

## 上游与许可

固定官方 [Full Stack FastAPI Template 0.12.0](https://github.com/fastapi/full-stack-fastapi-template/tree/84c5a9e11a9e58262599e3d772f5386924e02ca7)，commit `84c5a9e11a9e58262599e3d772f5386924e02ca7`，MIT，原 [LICENSE](LICENSE) 保留。

复用并适配上游 FastAPI/SQLModel/Argon2/JWT 账号基础、Alembic、React/Vite/shadcn 原生组件、OpenAPI SDK 生成与 pytest/Playwright 基础；去掉演示 Items、扩权用户管理、密码邮件、遥测和不适用部署文件。没有引入第二套 UI 或服务体系。依赖具体版本由 `uv.lock` 与 `bun.lock` 固定；上游依赖各自许可仍适用。

## 邮箱验证与恢复（T02）

注册事务先建立账号并耗用邀请，再通过标准库 SMTP 发送验证邮件；响应 201 的 `verification_sent` 区分交付成功/失败，SMTP 失败不会撤销已建立账号或恢复邀请码。用户随后登录自己的训练首页，未验证时只允许查本人信息、重发、确认验证和退出；管理员原有邀请权限不因验证而扩展。所有训练入口必须使用 `get_training_user`，目前 `/training/access` 仅验证这条共享边界。

- 链接是 256 位随机一次性凭证，数据库仅存 SHA-256 摘要、账号及原邮箱；默认 30 分钟（`VERIFICATION_EXPIRE_MINUTES`）。用户必须登录对应邮箱账号后点击确认，收到邮件/打开页面本身不改变状态。URL fragment 由页面读取后清除，不放到 HTTP 查询/访问日志；刷新丢失待确认链接时重新打开邮件即可。
- 成功重发使旧链接失效，每账号成功发送后 60 秒可重发；同账号发信与验证在 PostgreSQL 行锁下串行。验证成功删除凭证；重复/并发确认最多成功一次。发信失败保留此前有效链接；超时交付不明或邮件交付后数据库提交失败时，新链接可能无效，用户可重新发送。不保证 SMTP 与数据库分布式原子提交。
- 发送最多等待 5 秒连接/每次 socket 操作；未实现后台邮件队列或自动重试。注册响应丢失可先登录查看真实状态，不能凭页面报错认定注册失败。退出失败保留本机凭据供重试，不显示成功。
- `POST /users/me/verification-email` 返回 200（已交给收件服务/已经验证）、429（稍后重发）、503（发送失败，可重试）；`POST /users/me/verify-email` 接收 `{token}`，成功 200，格式错误 422，无效/过期/重放/邮箱不匹配 400。以上路径带 `/api/v1` 前缀，均要求有效会话（401）；训练未验证 403。发信/验证沿用每客户端每路径每分钟 60 次限制。
- `SMTP_HOST/SMTP_PORT/SMTP_FROM` 默认本机测试端；支持可配置 `SMTP_STARTTLS`、`SMTP_USER/SMTP_PASSWORD`，认证必须使用 TLS，证书由系统信任链校验。本轮仅执行 Mailpit 明文回环测试，未测试真实 SMTP、认证、外部投递或投递到达率；真实服务配置需另获授权。Mailpit 端口只能本机访问，邮件包含可验证凭证，勿公开收件服务。

并行本机测试可在 `.env` 指定 `DB_PORT`、对应 `DATABASE_URL`、`SMTP_PORT`、`MAILPIT_HTTP_PORT`、`FRONTEND_HOST`、`PLAYWRIGHT_BASE_URL`、`MAILPIT_URL`；运行 API 时使用对应端口。API 测试用 `MAILPIT_URL` 环境变量（默认 `http://127.0.0.1:18025`），例如 `MAILPIT_URL=http://127.0.0.1:18035 uv run --directory backend pytest tests -q`。浏览器配置自动读取 `.env`。测试无真实邮件；初始/重发失败用受控异常注入，正常路径从真实 SMTP 收件端读取邮件。

验证覆盖：API 的未登录/跨账号/伪造/过期/重放/并发确认、SMTP 失败恢复、退出旧令牌失效/其他设备有效；Playwright 的注册→本地收件→登录→错误链接→确认→准入→退出→旧凭据拒绝与退出网络失败恢复。无部署、无训练内容与模型调用验收。过期会话记录当前保留，数据库留存清理属于后续运维配置。

## 全栈能力目录（T06 #7）

邮箱验证后，首页通过 `GET /api/v1/capabilities/catalog` 展示版本 `fullstack-v1.0.0`：14 领域、29 个稳定叶子能力、三档定义与 42 个对照样例，覆盖原始范围的典型判断及加深方向。目录中技术背景描述给定材料的适用边界；它不是所有语言/框架的可用矩阵。样例明确尚未人工核验，不是正式训练题、隐藏评分答案或 #35–#40 所需的 84 个人工基准与真实模型评测。

- 单一来源是 `backend/app/capabilities/v1.json`，作为随代码发布的只读内容，无数据库副本、管理写入口或模型临时改前置路径。发布后保留旧版本文件和稳定 ID；语义、背景或前置变更发布新版本，后续轮次/证据保存所用目录版本，不静默改写旧记录。
- 叶子单独给出可观察判断标准，定档应用目录的三档标准及对应领域对照样例。样例 `capability_ids` 仅列实际涉及的判断，正式综合题仍必须逐项明确考察并单独评分，不能因组件出现就取证。
- 前置键明确为 `capability_id + difficulty + background_id`。`required` 全部满足，`alternatives` 的每组至少满足一项；不同背景/难度不能互换。API 读取不产生证据、解锁或等级变更。当前地图一律标「未验证」，不代表失败；#17/#18 接入真实证明与既有解锁记录，不能从浏览器自报值构造已验证集合。
- 基础节点均无先验能力证明要求；服务端启动检查引用、三档覆盖、所有依赖边无环和从空证据开始的逻辑可达性，坏目录拒绝启动。综合 API 幂等可走数据库不变量或消息防重替代路径，架构演进有两个分别必需的替代组，不强制全部前端后才学后端。
- 接口要求真实有效会话（401）及已验证邮箱（403），响应禁止缓存；没有自报/修改/解锁写入口（405）。加载失败可重试，读取失败保留已展示目录及筛选；原生展开项、领域选择和三档单选支持键盘，证明和训练入口由后续任务接入。

专项检查：`uv run --directory backend pytest tests/test_capabilities.py -q`；运行 API 后 `bun run --cwd frontend test capabilities.spec.ts`。图结构与确定性边界检查不证明目录教学质量；手机 320 CSS 像素及 200% 文本缩放截图位于被忽略的 `frontend/test-results/capability-map-mobile.png`。无部署、无真实模型或外部邮件调用。
## 个人模型配置（T04 #5）

邮箱验证后显示独立个人配置区域；未验证账号沿用首页的有限操作边界，配置 API 返回 403。每账号至多一套已保存配置，未配置返回 `null`，无默认 Key。首次及每次保存由页面明确确认运营者能解密、指定模型服务接收必要学习材料；服务地址改变会清除确认，必须重填 Key。管理员没有他人配置或 Key 回读入口。

- `GET /api/v1/model-config` 仅返回本人的 `version/service_url/model_id/has_key`，绝不返回 Key、密文或加密材料。所有成功配置响应 `Cache-Control: no-store`。
- `PUT /api/v1/model-config` 接收 `{service_url, model_id, api_key, expected_version, disclosure_accepted}`。首次 `expected_version: null`，修改传上次读到的 UUID；不一致 409，保留当前数据，不覆盖新版本。`api_key: null` 只可在地址未变时保留当前 Key；每次保存生成新 UUID（包括只改模型 ID），旧引用失效。
- `DELETE /api/v1/model-config?expected_version=UUID` 删除当前整套配置及在线密文；已不存在时幂等 204，版本变更时 409。UI 先确认再执行。不删除学习数据。重新保存使用新 UUID，旧引用不能复活。
- 保存仅校验本地输入并持久化；HTTPS（默认 443 或显式合法端口 1–65535）、无账号、查询、fragment，拒绝明显本地地址、内网 IP 及异常域名。**不解析 DNS、不向供应商发请求**，因此保存不是连通性或出站安全验收。实际出站的 DNS/重定向/代理/目标绑定由 T05 #6 每次连接验证；教学质量也未验证。
- 参数错误 422 不回显输入（含畸形 JSON）；401 要重新登录，403 未验证，409 要刷新重编，503 加密材料不可用／解密失败。前端提交后总是清空 Key，只保留普通输入；失败不会显示保存成功，不自动重试，不写 localStorage/sessionStorage。刷新配置会明确丢弃未保存编辑。

加密使用 `cryptography` 的 AES-256-GCM，随机 96 位 nonce，认证绑定账号 ID、配置 UUID、地址、模型 ID 和加密材料版本，防止搬运密文到别的账号或目的地。数据库只保存密文及非秘密版本标识；独立的 `MODEL_ENCRYPTION_KEYS` 由进程环境或仓库忽略的权限 0600 `.env` 提供，格式 `{"v1":"<32随机字节的标准Base64>"}`，`MODEL_ACTIVE_KEY_VERSION` 默认 `v1`。`scripts/init_local.py` 生成本机独立材料；已有 `.env` 不覆盖。没有有效材料时账号功能仍可用，但保存/使用凭据失败关闭，绝不退回 JWT SECRET_KEY 或明文存储。环境文件与数据库备份必须分开保管，服务器运营者技术上仍能解密；不要把真实 Key 用于本地测试。

旧本机环境需在保留原 `.env` 的前提下，由操作者新增独立随机材料。轮换先保留旧版本，再增加新材料及切换 `MODEL_ACTIVE_KEY_VERSION`，重启 API/worker；配置下一次保存（同地址可留空 Key）会以新版本重新加密。确认数据库不再引用旧版本，并满足最长 30 天备份窗口后，才可退役旧材料。丢失某版本材料无法还原该版 Key，用户可重新填写替换或删除。已用伪材料验证新旧版本共存、重加密、旧材料移除后的读取，以及材料缺失/密文篡改失败关闭。

后续调用模块统一使用 `app.model_config.service.credential_for_call(session, user_id, version)`：`user_id` 必须来自服务端认证或已核验归属的持久任务，不能信任请求自报身份；持久任务只存账号和配置版本。用独立 Session/事务包住上下文和一次真实请求，禁止在上下文外缓存/使用明文；里面再做实际出站目的地安全校验。上下文与保存/删除锁定同一账号行，旧版本/跨账号引用 409；每次请求均重新验证账号可用、邮箱验证及当前版本。当前简化为持锁覆盖一次调用，调用方必须限制在 120 秒内；保存/删除可能等待这次请求结束，成功后旧版本不能新派发。尚无实际模型调用或运行任务；#15 再实现停止/尝试取消及迟到结果标识，当前不声称已经实现取消。

本地验证使用 bp-issue-5 隔离 PostgreSQL 和伪 Key：25 项专项 API 检查包含 fresh Python 进程重读、替换/删除/重建撤销、跨用户、格式错误不回显、加密材料缺失/轮换/认证篡改及并发单胜、调用锁顺序与已缓存账号被停用后的拒绝；Playwright 检查真实邮箱验证→保存→刷新→替换失败恢复→替换→删除与手机宽度、浏览器存储无 Key。未建立备份或生产部署，不能将本地删行视为备份恢复验收；启用备份恢复前必须实现删除重放，禁止恢复旧 Key 后直接开放调用（后续数据留存/部署票）。
