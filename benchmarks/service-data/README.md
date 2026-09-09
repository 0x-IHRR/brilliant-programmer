# 服务与数据基准候选 v0.1

本批仅为 #36 内部准备。18 个案例、36 个标签和全部变式由 AI 起草，尚待真人核验；`origin=ai_draft`、`review_status=pending_human_review`、`human_review=null` 是可机器检查的状态。没有人工签名或真实模型成绩，不能供 #40 当作已人工核验基准，也不能 Closes #36。

范围为服务端/API、数据/数据库、缓存/异步任务，每领域两家族、基础/进阶/综合三档。绑定现有 fullstack-v1.0.0 的 api.boundary、api.idempotency、data.integrity、data.query、async.cache、async.jobs 及相应 evidence-v1 背景；未新增公共目录或前置。每题一个联合判断，只对明确主能力记候选证据；涉及的其他组件不自动通过。综合档是否充分覆盖复杂度仍须人工判断，不以篇幅或标签认证。

所有运行日志、时间、权限、数量和外部结果均是明确的教学假设。官方来源只支撑语言、协议或产品行为边界，不能称其观察过本题运行。

## 来源与人工复核

来源于实际读取的 RFC6750/RFC9111、PostgreSQL17、RabbitMQ4.1、OWASP API1:2023 和 Stripe 幂等 API 文档。读取日期2026-09-10，每份完整响应SHA-256写入version，定位写入locator；版本化路径或固定RFC编号优先，Stripe为明确读取快照，不宣称所有API版本长期相同。完整网页未入库。

Source.text 只存空白折叠后的短逐字摘录，用[…]分隔。Source.locator含明确标注的AI中文规范摘要，保存适用条件与例外；它不是原文引用，也仍待人工核验。每题及变式选择相关摘录而非固定来源首片，必要的不同来源分别引用。后续受控传输必须同时保URL/version/locator/text并核实际模型请求，不能只送text而丢限定。

真人应逐条确认：版本与定位可复查、假设充分且不冲突、选项与标签成立、补证结论没有误标错误、变式确实改变决策而非只换措辞、帮助方向适当。`REVIEW.md`便于逐条审阅；精确冻结对象是JSON。机器校验只确认结构/引用/绑定契约，不能证明自然语言推理真实。

## 软件边界

复用现有 Source/Candidate/Answer/GradingCandidate、validate_candidate、validate_grading、assess_novelty；本批载入封装仅强制待核验状态，不新增评分体系或评测runner。36标签包含各例可接受与明确错误对照；部分正确结论本身是先补证，未把未知外部结果强判失败。

从 backend 运行 `../.venv/bin/pytest tests/test_service_data_benchmarks.py --noconftest -q`。来源、答案、正反变式、范围和伪人工签核拒绝均须通过。真实受控API/UI尚待接入验证；不把纯检查称为全流程或真实模型质量通过。产品共享 GET 一致性修复由 #25 负责，本票不并行修改公共代码。

完整验收仍需18个人工核验案例、36人工标注及依据，以及明确授权后的真实模型流程与质量证据。实际可用语言/框架矩阵应来自这些证据；当前没有部署、真实付费调用或真实对外发信。
