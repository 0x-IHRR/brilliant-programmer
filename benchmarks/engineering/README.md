# 业务、架构与协作候选核验材料

内部准备，Refs #38。全部为AI起草，未人工核验；`origin=ai_draft`、`review_status=pending_human_review`且`human_review=null`，每份答案标签也单独标待核验。不得把生产schema通过、AI审查或受控模型运行结果称为人工签核、评分质量或学习效果证明。

本批18例：需求、架构、团队三个领域，每领域两个家族×基础/进阶/综合，各含可接受与明确错误答案，共36标签候选。`candidates.json`直接使用生产Candidate/Answer/GradingCandidate；`sources.json`使用Source。`REVIEW.md`供真人逐条核对原题、变式、来源、反例和帮助界限，不自动认可标签。

| 现有叶子/家族 | 基础 → 进阶 → 综合的候选范围 |
| --- | --- |
| requirements.acceptance | 可观察保存结果 → 支付异常与状态互斥 → 跨渠道时序与重放规则 |
| requirements.tradeoff | 质量与范围 → 用户目标和实现成本 → 目标过时与沉没成本 |
| architecture.responsibility | 职责与技术层 → 限界上下文词义 → 状态所有权、共同发布与接口耦合 |
| architecture.evolution | 渐进路由适用条件 → 新旧读写兼容 → 门面单点及跨系统语义恢复 |
| team.review | AI摘要与真实权限diff → 测试能否拦住原缺陷 → AI意见、人工检查和版本绑定 |
| team.handoff | 已恢复和待办 → 事实、原因假设与预防动作 → 多团队对账、授权和迟到路径 |

仅绑定目录fullstack-v1.0.0已有requirements-evidence-v1、architecture-evidence-v1、team-evidence-v1；不新增目录项、不声称所有框架/团队流程可用。每题一个明确联合判断，只给该主能力落点；提及支付、数据库或网络不额外授证。三档是待核候选深度，不能仅凭字段值认证覆盖充分。标准答案只是一个见证：符合冻结约束的白话或其他有效方案应同等接受，不做关键词/逐字答案匹配。正确补证判断不会因为尚无运行证据而标错；题目明确考察当前可支持的下一步。

所有日志、角色、业务约束、性能和验证结果均为显式教学假设。官方资料只支持规则，不证明这些合成运行发生过。来源实际读取日期2026-09-10；Scrum固定November2020，Google SRE固定2016书章，其他官方滚动文档保存日期及响应SHA256。SHA用于定位抓取版本，不是语义质量证明。短原文在`text`，适用条件与限制在`locator`，后者明确为AI中文改写、非逐字引句、待人工核验。传输给受控provider时必须保完整url/version/locator/text，不可只留下短摘录。

实质变式改变可定位事实、条件与决策理由；仅改标题的对照保其余内容不变。引用定位的逐case测试用于防编辑错绑，不是自动语义认证。方向解释含当前因果/结论；中性和不确定文本均为待人工验证候选，实际资格仍由生产内容检查与交付事实判定，不由按钮/本文件自报。

来源以NASA需求清单、Scrum Guide、Microsoft Azure Architecture Center、Google Engineering Practices、GitHub Copilot文档及Google SRE书章为基础。引用短摘录和改写，未复制整篇官方文章。个别来源的组织流程只在题目明确采用该流程时适用，不作全行业强制标准。

验证：backend目录 `../.venv/bin/pytest tests/test_engineering_benchmarks.py --noconftest -q`。本阶段只校验18例/36标签与实际生产契约、实质变化和伪人工状态拒绝；真实受控API/UI另以新增测试完成。完整后端集合按协调等待#25共享GET一致性修复整合后执行；没有真实付费模型、对外发信、联系他人或部署。最终仍需真人逐条核验及获授权后的真实模型质量评测，内部部分draft PR不Closes本票。
