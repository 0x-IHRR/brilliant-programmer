# 项目模块学习路线（Issue 23）

## 实现边界

复用项目安全读取器、Topic 的版本/CAS/两阶段检查与持久队列、原题提交/评分/帮助和独立检验。路线分析冻结本次 ProjectRun 的 Snapshot 与 ProjectMap；选定模块再冻结 commit、blob、路径、行号、精确引用和目标。未读或缺少必要材料的模块明确列出缺项，不能开题；其他已核模块可以继续。地图顺序不替代目录中的 ALL/OR 前置条件。

来源文本证明的是代码内容，不证明运行行为。生成结果区分代码事实、教学假设与合成日志；单独检查实际来源与材料充分性。来源标记和模型检查均不构成人工语义认证。未确认路线不生成题目，私有候选与材料只在完成发布后公开；评估保留完整冻结来源。重排保留节点身份，编辑创建新版本，未保存输入阻止确认/开题并保留冲突输入。独立检验继续使用完整历史协议及现有入口准入；不把改名、hash 或模型自报陌生当证明。

没有实现 Issue 24 的更新/删除，也不执行目标仓库的代码、依赖、hooks 或脚本。现有语法地图主要能核实 Python 的语法结构；其他语言/未读取模块不因此成为已证实代码事实。

## 一次真实公开入口证据

公开项目 `pallets/itsdangerous`，固定 commit `672971d66a2ef9f85151e53283113f33d642dabd`，模块 `src/itsdangerous/timed.py`，blob `52deeeab44f09c1c7f54438c9f48f54d61366085`。保留的教学必要片段为 132–158 行，检查 `age > max_age` 边界；假设签名有效、教学时钟与输入，不声称实际执行。

通过真实 `/projects` API、独立进程 worker、生产 GitHub DNS/IP/HTTPS 安全 transport 完成读取，再经路线分析、确认、题目发布、正式作答与评分恢复记录。27 次匿名 GitHub 请求，58,638 字节，整条在线验证链路耗时 24.58 秒；6 次受控本地 TLS 模型请求。模型目的地仅本地伪服务，GitHub 仍走真实生产安全 transport；未使用真实 Key 或付费模型。测量是本次具体仓库/提交的证据，不代表任意语言、任意规模或教学质量。

本机证据：`/tmp/bp-issue-23-artifacts/online-entry.json`，project `e5fac801-5190-4d7f-92c6-8867bf482cb2`，topic `d10ad872-4d9f-421e-b6e8-926b6b438a7a`，training `b2378935-a80e-44e1-8f38-0efc4baa4797`。`tests/project_training_public_probe.py` 为显式手工在线验证，不加入离线 CI。CI 使用同一固定 commit 的源码片段 fixture，通过实际 API/队列/数据库/受控 TLS，不把 fixture 当第二次线上验证。

## 冻结前检查记录

实际通过：完整项目路线到反馈 1 项；CAS/不可变/不足材料 3 项；来源分析停止恢复与独立帮助交付 2 项；完整 70 条项目历史协议 3 项；固定公开源码离线完整流程 1 项。错误结果/新 Key 出站检查合并运行 9 通过、1 测试读取不存在公开字段失败；改查持久 TopicJob 的 authentication 后该项单独通过。此前首次收集因错误 cwd 缺环境配置退出，不计测试通过。

真实浏览器主链路 1 项已通过：320 宽度、200% 字号、键盘 Enter/Space、草稿真实保存、提交反馈与刷新恢复。截图位于 `/tmp/bp-issue-23-artifacts/` 的 `project-training-320.png`、`project-training-200.png`、`project-feedback-320.png`。最终新增检查和完整回归会补记，以上不能相加冒称一个无重叠全套总数。

人工教学/真实模型准确性、跨语言全面覆盖、历史规模性能尚未验收。新迁移 0026 当前接 0024；与并行 0025 合并时必须按真实主线单 head 串接，不 stamp。没有部署。

## 完整后端 checkpoint

固定后端 c2100f5 本轮完整运行：795 通过、2 失败，1779.00 秒。两项均为既有 `test_phase_budgets_malformed_correction_and_transient_backoff`：六调用退避场景在原 15 秒等待结束时已持久记录五次且第六次请求已发出；畸形纠正场景在原 15 秒结束时仍 queued、零调用。保留原等待和全部断言，后续单项复验另记，不能把本次写成 797 全通过。完整日志 `/tmp/bp-issue-23-artifacts/full-backend.log`；本轮使用默认 pytest-571 临时目录，未主动清理，后续定向使用本票唯一 `--basetemp`。
