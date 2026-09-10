# 逐条人工复核待办

全部为 AI 草稿，尚无人类签核。以下便于审阅，JSON保留完整结构；此清单不自动认可标签。

## requirements.acceptance-1 — 保存成功的含糊验收

状态：pending_human_review；技术背景：requirements-evidence-v1；档位：基础

**原题**

运营人员点击保存后需要下次登录仍看到配置；需求只写“保存体验友好”，尚未约定失败响应和输入保留。

可接受：补明确参与者、触发、重登后读取及失败保输入规则，再评审验收。

明确错误：按钮显示绿色即可宣布所有保存要求完成。

依据候选：外观无法代替持久结果，需把正常和异常行为写成可观察要求。

反例：反例：运营人员点击保存后需要下次登录仍看到配置；需求只写“保存体验友好”，尚未约定失败响应和输入保留。 因此“按钮显示绿色即可宣布所有保存要求完成。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：Are the requirements clear and unambiguous?

**实质变式候选**

保存成功与失败保输入已明确；新增断网时响应丢失，服务端是否已保存未知且禁止重复创建。

可接受：保原验收，补失响应后查询原请求结果及重试防重契约。

明确错误：按钮显示绿色即可宣布所有保存要求完成。

依据候选：新不确定窗口不由原成功/失败二分覆盖，应单独规定恢复行为。

反例：反例：保存成功与失败保输入已明确；新增断网时响应丢失，服务端是否已保存未知且禁止重复创建。 因此“按钮显示绿色即可宣布所有保存要求完成。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：Are there error detection, reporting, handling, and recovery requirements?

变化依据：由“运营人员点击保存后需要下次登录仍看到配置；需求只写“保存体验友好”，尚未约定失败响应和输入保留。”变为“保存成功与失败保输入已明确；新增断网时响应丢失，服务端是否已保存未知且禁止重复创建。”，故“补明确参与者、触发、重登后读取及失败保输入规则，再评审验收。”改为“保原验收，补失响应后查询原请求结果及重试防重契约。”。

仅改名反例：保存成功的含糊验收（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：外观无法代替持久结果，需把正常和异常行为写成可观察要求。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## requirements.acceptance-2 — 状态转移缺少失败边界

状态：pending_human_review；技术背景：requirements-evidence-v1；档位：进阶

**原题**

买家付款成功才发货；当前要求只列待付和已付，未说明支付响应丢失与重复回调，且同订单不得重复发货。

可接受：补回调身份、失响应查询和允许发货条件，并明确重复消息不重复动作。

明确错误：收到任意付款按钮点击就改已付并发货。

依据候选：支付意图不是付款事实，异常与重放必须服从不可重复发货的冻结约束。

反例：反例：买家付款成功才发货；当前要求只列待付和已付，未说明支付响应丢失与重复回调，且同订单不得重复发货。 因此“收到任意付款按钮点击就改已付并发货。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：Are there error detection, reporting, handling, and recovery requirements?

**实质变式候选**

已核同订单重复回调无重复发货；新规则允许发货前退款，退款成功消息与发货请求可并发。

可接受：保已证防重，补退款与发货互斥条件及冲突时可观察结果。

明确错误：收到任意付款按钮点击就改已付并发货。

依据候选：新竞争是业务状态互斥问题，原消息防重不覆盖退款后的合法动作。

反例：反例：已核同订单重复回调无重复发货；新规则允许发货前退款，退款成功消息与发货请求可并发。 因此“收到任意付款按钮点击就改已付并发货。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：Are there error detection, reporting, handling, and recovery requirements?

变化依据：由“买家付款成功才发货；当前要求只列待付和已付，未说明支付响应丢失与重复回调，且同订单不得重复发货。”变为“已核同订单重复回调无重复发货；新规则允许发货前退款，退款成功消息与发货请求可并发。”，故“补回调身份、失响应查询和允许发货条件，并明确重复消息不重复动作。”改为“保已证防重，补退款与发货互斥条件及冲突时可观察结果。”。

仅改名反例：状态转移缺少失败边界（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：支付意图不是付款事实，异常与重放必须服从不可重复发货的冻结约束。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## requirements.acceptance-3 — 跨渠道会员资格冲突

状态：pending_human_review；技术背景：requirements-evidence-v1；档位：综合

**原题**

网页承诺取消后立即停费，批处理仍按月初快照扣费；客服允许当日恢复，时区和生效序号未约定，不能默默多收费。

可接受：列明取消/恢复/扣费的生效顺序与时区、补偿和验收样例，未澄清前不宣布一致。

明确错误：只测试网页取消提示就认定所有渠道收费一致。

依据候选：跨渠道冲突需显式时间及异常规则，界面提示不能决定后台合法计费。

反例：反例：网页承诺取消后立即停费，批处理仍按月初快照扣费；客服允许当日恢复，时区和生效序号未约定，不能默默多收费。 因此“只测试网页取消提示就认定所有渠道收费一致。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：Are the requirements clear and unambiguous?

**实质变式候选**

双方已确认服务器序号顺序和当日规则，回放扣费一致；新增离线代理可能重复提交旧恢复请求。

可接受：保已确认规则，增加旧请求身份及幂等/过时拒绝验收，不重开已决时区。

明确错误：只测试网页取消提示就认定所有渠道收费一致。

依据候选：规则明确后新入口带来重放边界，不能仅重复旧渠道测试。

反例：反例：双方已确认服务器序号顺序和当日规则，回放扣费一致；新增离线代理可能重复提交旧恢复请求。 因此“只测试网页取消提示就认定所有渠道收费一致。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：Are there error detection, reporting, handling, and recovery requirements?

变化依据：由“网页承诺取消后立即停费，批处理仍按月初快照扣费；客服允许当日恢复，时区和生效序号未约定，不能默默多收费。”变为“双方已确认服务器序号顺序和当日规则，回放扣费一致；新增离线代理可能重复提交旧恢复请求。”，故“列明取消/恢复/扣费的生效顺序与时区、补偿和验收样例，未澄清前不宣布一致。”改为“保已确认规则，增加旧请求身份及幂等/过时拒绝验收，不重开已决时区。”。

仅改名反例：跨渠道会员资格冲突（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：跨渠道冲突需显式时间及异常规则，界面提示不能决定后台合法计费。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## requirements.tradeoff-1 — 日期固定不等于可降低质量

状态：pending_human_review；技术背景：requirements-evidence-v1；档位：基础

**原题**

采用Scrum；本Sprint目标是可靠付款，已约定付款失败不得丢订单；配色需求新增但容量只够一项。

可接受：与Product Owner按目标协商配色范围，保付款安全质量和完成定义。

明确错误：为同时交付配色和付款删掉失败保单要求并仍称完成。

依据候选：可调整范围不意味着降低既定质量，选择需服从受益目标和容量约束。

反例：反例：采用Scrum；本Sprint目标是可靠付款，已约定付款失败不得丢订单；配色需求新增但容量只够一项。 因此“为同时交付配色和付款删掉失败保单要求并仍称完成。”不成立。

来源：[scrum](https://scrumguides.org/scrum-guide.html)；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done; response-sha256:64aade688c3f2bceb1051268310e1cdcf503ac424e052a07414f60cabea8bcc0；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done。规范摘要（AI中文改写，待人工核验，非逐字引句）：范围可以随学习与Product Owner协商，但不损害Sprint Goal或降低质量。目标过时可由Product Owner取消Sprint；时间压力不使未达Definition of Done的工作变成完成。此框架只适用于题目声明采用Scrum的团队。

本判断短引定位：Quality does not decrease

**实质变式候选**

付款质量已满足，配色是低成本必要无障碍修复且不影响目标，容量充足。

可接受：纳入已核可承受修复并保验收，不机械拒绝所有Sprint内变化。

明确错误：为同时交付配色和付款删掉失败保单要求并仍称完成。

依据候选：风险与容量变化后可调整范围，固定目标不代表工作清单完全不能变。

反例：反例：付款质量已满足，配色是低成本必要无障碍修复且不影响目标，容量充足。 因此“为同时交付配色和付款删掉失败保单要求并仍称完成。”不成立。

来源：[scrum](https://scrumguides.org/scrum-guide.html)；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done; response-sha256:64aade688c3f2bceb1051268310e1cdcf503ac424e052a07414f60cabea8bcc0；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done。规范摘要（AI中文改写，待人工核验，非逐字引句）：范围可以随学习与Product Owner协商，但不损害Sprint Goal或降低质量。目标过时可由Product Owner取消Sprint；时间压力不使未达Definition of Done的工作变成完成。此框架只适用于题目声明采用Scrum的团队。

本判断短引定位：without affecting the Sprint Goal

变化依据：由“采用Scrum；本Sprint目标是可靠付款，已约定付款失败不得丢订单；配色需求新增但容量只够一项。”变为“付款质量已满足，配色是低成本必要无障碍修复且不影响目标，容量充足。”，故“与Product Owner按目标协商配色范围，保付款安全质量和完成定义。”改为“纳入已核可承受修复并保验收，不机械拒绝所有Sprint内变化。”。

仅改名反例：日期固定不等于可降低质量（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：可调整范围不意味着降低既定质量，选择需服从受益目标和容量约束。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## requirements.tradeoff-2 — 用户目标与实现偏好

状态：pending_human_review；技术背景：requirements-evidence-v1；档位：进阶

**原题**

业务要将高峰查询等待降到可接受范围；提案直接要求拆十个服务，无等待分解、成本预算或验收阈值。

可接受：先明确用户结果和约束，比较最小测量/优化与拆分成本，不承诺未知收益。

明确错误：十个服务数量达到就说明等待问题解决。

依据候选：实现数量不是用户结果，尚无证据说明拆分能改善真正瓶颈。

反例：反例：业务要将高峰查询等待降到可接受范围；提案直接要求拆十个服务，无等待分解、成本预算或验收阈值。 因此“十个服务数量达到就说明等待问题解决。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：state the problem not the solution

**实质变式候选**

已证等待主要来自可缓存的只读查询；约定允许30秒旧数据，但余额查询必须实时。

可接受：按一致性边界比较只缓存允许陈旧部分的成本与收益，保余额实时验收。

明确错误：十个服务数量达到就说明等待问题解决。

依据候选：实际等待与容忍度已知后可以做受约束取舍，不能把局部容忍推广到余额。

反例：反例：已证等待主要来自可缓存的只读查询；约定允许30秒旧数据，但余额查询必须实时。 因此“十个服务数量达到就说明等待问题解决。”不成立。

来源：[nasa](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/)；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10; response-sha256:35cd14f4a4f7b5bd6db7b4133f0eaee4c975da5ba33b2f61626254f1c1815468；NASA Systems Engineering Handbook Appendix C, C.2–C.4; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：需求应明确主体、所需结果、量化范围与异常响应，避免含糊词。WHAT/HOW区别用于避免无依据指定实现，不排除已确认的设计约束；假设须确认且需求应可验证、可追溯。

本判断短引定位：state the problem not the solution

变化依据：由“业务要将高峰查询等待降到可接受范围；提案直接要求拆十个服务，无等待分解、成本预算或验收阈值。”变为“已证等待主要来自可缓存的只读查询；约定允许30秒旧数据，但余额查询必须实时。”，故“先明确用户结果和约束，比较最小测量/优化与拆分成本，不承诺未知收益。”改为“按一致性边界比较只缓存允许陈旧部分的成本与收益，保余额实时验收。”。

仅改名反例：用户目标与实现偏好（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：实现数量不是用户结果，尚无证据说明拆分能改善真正瓶颈。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## requirements.tradeoff-3 — 原目标过时与继续投入

状态：pending_human_review；技术背景：requirements-evidence-v1；档位：综合

**原题**

采用Scrum；Sprint目标是接入渠道A，但合同确认A将停止服务，目标已失商业意义；剩余三天且有沉没投入。

可接受：向Product Owner呈现目标过时证据及替代成本，由其决定是否取消并重新规划。

明确错误：只因已投入两周就继续到原截止日并宣布实现了有效目标。

依据候选：已发生投入不恢复目标价值，Scrum允许由Product Owner在目标过时后取消。

反例：反例：采用Scrum；Sprint目标是接入渠道A，但合同确认A将停止服务，目标已失商业意义；剩余三天且有沉没投入。 因此“只因已投入两周就继续到原截止日并宣布实现了有效目标。”不成立。

来源：[scrum](https://scrumguides.org/scrum-guide.html)；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done; response-sha256:64aade688c3f2bceb1051268310e1cdcf503ac424e052a07414f60cabea8bcc0；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done。规范摘要（AI中文改写，待人工核验，非逐字引句）：范围可以随学习与Product Owner协商，但不损害Sprint Goal或降低质量。目标过时可由Product Owner取消Sprint；时间压力不使未达Definition of Done的工作变成完成。此框架只适用于题目声明采用Scrum的团队。

本判断短引定位：if the Sprint Goal becomes obsolete

**实质变式候选**

渠道确认继续有效且用户价值不变，只是估算不足；删非必要范围可保目标和质量。

可接受：协商缩小范围保持目标和质量，不把一次估算偏差当成目标过时。

明确错误：只因已投入两周就继续到原截止日并宣布实现了有效目标。

依据候选：目标仍有效时调整工作范围与取消目标不同，需按变化后的证据选择。

反例：反例：渠道确认继续有效且用户价值不变，只是估算不足；删非必要范围可保目标和质量。 因此“只因已投入两周就继续到原截止日并宣布实现了有效目标。”不成立。

来源：[scrum](https://scrumguides.org/scrum-guide.html)；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done; response-sha256:64aade688c3f2bceb1051268310e1cdcf503ac424e052a07414f60cabea8bcc0；Scrum Guide November 2020, The Sprint / Sprint Goal / Definition of Done。规范摘要（AI中文改写，待人工核验，非逐字引句）：范围可以随学习与Product Owner协商，但不损害Sprint Goal或降低质量。目标过时可由Product Owner取消Sprint；时间压力不使未达Definition of Done的工作变成完成。此框架只适用于题目声明采用Scrum的团队。

本判断短引定位：without affecting the Sprint Goal

变化依据：由“采用Scrum；Sprint目标是接入渠道A，但合同确认A将停止服务，目标已失商业意义；剩余三天且有沉没投入。”变为“渠道确认继续有效且用户价值不变，只是估算不足；删非必要范围可保目标和质量。”，故“向Product Owner呈现目标过时证据及替代成本，由其决定是否取消并重新规划。”改为“协商缩小范围保持目标和质量，不把一次估算偏差当成目标过时。”。

仅改名反例：原目标过时与继续投入（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：已发生投入不恢复目标价值，Scrum允许由Product Owner在目标过时后取消。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## architecture.responsibility-1 — 按文件夹还是业务职责拆分

状态：pending_human_review；技术背景：architecture-evidence-v1；档位：基础

**原题**

订单Controller/Service/DAO每次规则变化都一起改且共享订单状态；拟按三技术层拆成远程服务，没有独立业务需求。

可接受：先保订单职责内聚，识别实际变化边界，不因三层文件夹就拆三个远程服务。

明确错误：每个技术层各一服务就自动低耦合。

依据候选：共同业务变化跨三服务仍强耦合，部署数量不能代替职责边界。

反例：反例：订单Controller/Service/DAO每次规则变化都一起改且共享订单状态；拟按三技术层拆成远程服务，没有独立业务需求。 因此“每个技术层各一服务就自动低耦合。”不成立。

来源：[domain](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis)；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10; response-sha256:bd02ca5aea722599b07afcba12453a05330555a63c57a1197eb60ffb175cb17b；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按业务职责而非技术层机械拆分；同一词在不同限界上下文可能有不同含义。用共同变化、状态归属和接口约束检查内聚/耦合；没有机械算法保证正确划界，也不要求每个上下文立即独立部署。

本判断短引定位：Design microservices around business capabilities

**实质变式候选**

通知策略由独立团队频繁调整，只读已提交订单事件且不拥有订单状态，可延迟。

可接受：评估把通知作为独立职责，冻结事件及失败隔离契约再决定部署。

明确错误：每个技术层各一服务就自动低耦合。

依据候选：独立变化与状态归属支持新边界，但仍需验证接口和运行成本。

反例：反例：通知策略由独立团队频繁调整，只读已提交订单事件且不拥有订单状态，可延迟。 因此“每个技术层各一服务就自动低耦合。”不成立。

来源：[domain](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis)；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10; response-sha256:bd02ca5aea722599b07afcba12453a05330555a63c57a1197eb60ffb175cb17b；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按业务职责而非技术层机械拆分；同一词在不同限界上下文可能有不同含义。用共同变化、状态归属和接口约束检查内聚/耦合；没有机械算法保证正确划界，也不要求每个上下文立即独立部署。

本判断短引定位：without updating other services at the same time

变化依据：由“订单Controller/Service/DAO每次规则变化都一起改且共享订单状态；拟按三技术层拆成远程服务，没有独立业务需求。”变为“通知策略由独立团队频繁调整，只读已提交订单事件且不拥有订单状态，可延迟。”，故“先保订单职责内聚，识别实际变化边界，不因三层文件夹就拆三个远程服务。”改为“评估把通知作为独立职责，冻结事件及失败隔离契约再决定部署。”。

仅改名反例：按文件夹还是业务职责拆分（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：共同业务变化跨三服务仍强耦合，部署数量不能代替职责边界。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## architecture.responsibility-2 — 同名账户不是同一模型

状态：pending_human_review；技术背景：architecture-evidence-v1；档位：进阶

**原题**

登录账户保存凭据与封禁状态，财务账户保存借贷与结算规则；同叫account就拟共用可写表和状态字段。

可接受：分别明确两个语境的词义、所有权与接口，避免把封禁直接等同财务结清。

明确错误：字段同名足以证明状态规则可以完全共享。

依据候选：同一词在不同业务语境可有不同含义，直接共享可写状态会混淆不变量。

反例：反例：登录账户保存凭据与封禁状态，财务账户保存借贷与结算规则；同叫account就拟共用可写表和状态字段。 因此“字段同名足以证明状态规则可以完全共享。”不成立。

来源：[domain](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis)；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10; response-sha256:bd02ca5aea722599b07afcba12453a05330555a63c57a1197eb60ffb175cb17b；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按业务职责而非技术层机械拆分；同一词在不同限界上下文可能有不同含义。用共同变化、状态归属和接口约束检查内聚/耦合；没有机械算法保证正确划界，也不要求每个上下文立即独立部署。

本判断短引定位：same word (like account ) has different meanings

**实质变式候选**

业务确认两模块其实管理同一订阅合同与同一状态机，总是共同发布，所谓独立规则不存在。

可接受：先统一已确认的合同模型，别凭团队命名强拆两个相同状态所有者。

明确错误：字段同名足以证明状态规则可以完全共享。

依据候选：新证据表明语义与变化一致，不能把上下文划分口号代替领域核对。

反例：反例：业务确认两模块其实管理同一订阅合同与同一状态机，总是共同发布，所谓独立规则不存在。 因此“字段同名足以证明状态规则可以完全共享。”不成立。

来源：[domain](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis)；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10; response-sha256:bd02ca5aea722599b07afcba12453a05330555a63c57a1197eb60ffb175cb17b；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按业务职责而非技术层机械拆分；同一词在不同限界上下文可能有不同含义。用共同变化、状态归属和接口约束检查内聚/耦合；没有机械算法保证正确划界，也不要求每个上下文立即独立部署。

本判断短引定位：without updating other services at the same time

变化依据：由“登录账户保存凭据与封禁状态，财务账户保存借贷与结算规则；同叫account就拟共用可写表和状态字段。”变为“业务确认两模块其实管理同一订阅合同与同一状态机，总是共同发布，所谓独立规则不存在。”，故“分别明确两个语境的词义、所有权与接口，避免把封禁直接等同财务结清。”改为“先统一已确认的合同模型，别凭团队命名强拆两个相同状态所有者。”。

仅改名反例：同名账户不是同一模型（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：同一词在不同业务语境可有不同含义，直接共享可写状态会混淆不变量。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## architecture.responsibility-3 — 订单履约与结算的同步耦合

状态：pending_human_review；技术背景：architecture-evidence-v1；档位：综合

**原题**

履约与结算各有独立规则，但一方每次变更要求另两模块同步发布；订单关闭直接写三方状态，部分写成功会不一致。

可接受：沿真实调用和状态所有权梳理不变量，先定义各自提交及协调失败规则再划界。

明确错误：把三个模块搬到三台机器即可消除共同发布与部分成功。

依据候选：物理拆分不解除语义与写入耦合，跨边界协议必须支持真实业务一致性。

反例：反例：履约与结算各有独立规则，但一方每次变更要求另两模块同步发布；订单关闭直接写三方状态，部分写成功会不一致。 因此“把三个模块搬到三台机器即可消除共同发布与部分成功。”不成立。

来源：[domain](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis)；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10; response-sha256:bd02ca5aea722599b07afcba12453a05330555a63c57a1197eb60ffb175cb17b；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按业务职责而非技术层机械拆分；同一词在不同限界上下文可能有不同含义。用共同变化、状态归属和接口约束检查内聚/耦合；没有机械算法保证正确划界，也不要求每个上下文立即独立部署。

本判断短引定位：without updating other services at the same time

**实质变式候选**

共同写入已移除；履约事件有版本且结算可延迟，但消费者仍依赖提供方内部字段名。

可接受：保已隔离写入，补稳定事件契约和兼容验证，针对剩余字段耦合改进。

明确错误：把三个模块搬到三台机器即可消除共同发布与部分成功。

依据候选：已有状态边界有效不等于接口耦合消失，应针对剩余共同变化修正。

反例：反例：共同写入已移除；履约事件有版本且结算可延迟，但消费者仍依赖提供方内部字段名。 因此“把三个模块搬到三台机器即可消除共同发布与部分成功。”不成立。

来源：[domain](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis)；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10; response-sha256:bd02ca5aea722599b07afcba12453a05330555a63c57a1197eb60ffb175cb17b；Microsoft Azure Architecture Center, Domain analysis / bounded contexts; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按业务职责而非技术层机械拆分；同一词在不同限界上下文可能有不同含义。用共同变化、状态归属和接口约束检查内聚/耦合；没有机械算法保证正确划界，也不要求每个上下文立即独立部署。

本判断短引定位：without updating other services at the same time

变化依据：由“履约与结算各有独立规则，但一方每次变更要求另两模块同步发布；订单关闭直接写三方状态，部分写成功会不一致。”变为“共同写入已移除；履约事件有版本且结算可延迟，但消费者仍依赖提供方内部字段名。”，故“沿真实调用和状态所有权梳理不变量，先定义各自提交及协调失败规则再划界。”改为“保已隔离写入，补稳定事件契约和兼容验证，针对剩余字段耦合改进。”。

仅改名反例：订单履约与结算的同步耦合（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：物理拆分不解除语义与写入耦合，跨边界协议必须支持真实业务一致性。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## architecture.evolution-1 — 新旧入口同时在线

状态：pending_human_review；技术背景：architecture-evidence-v1；档位：基础

**原题**

旧订单服务需持续可用；可以按路径拦截，计划只迁移只读查询，写入仍由旧服务负责且新读兼容旧格式。

可接受：用可控门面逐步切只读路径并验证回退，保旧写入入口。

明确错误：先删旧服务再验证新只读路径，以为数据自然兼容。

依据候选：渐进切换依赖新旧共存和资源兼容，旧职责未迁移时不能提前删除。

反例：反例：旧订单服务需持续可用；可以按路径拦截，计划只迁移只读查询，写入仍由旧服务负责且新读兼容旧格式。 因此“先删旧服务再验证新只读路径，以为数据自然兼容。”不成立。

来源：[strangler](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10; response-sha256:e06f64b415f808e81e356a76d8caf41fb92728cb747ef4b42f3aac5617a90792；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：渐进迁移依赖可拦截路由与新旧共存；要处理共同数据/依赖的兼容，不以切流量假定旧写入已停止。门面自身可能成为单点或瓶颈；不能拦截请求时此模式可能不适用。渐进方案需比较临时成本及迁移风险，不承诺自动零停机。

本判断短引定位：both systems can access these resources

**实质变式候选**

客户端直连硬编码且无法拦截，旧源代码不可修改；原门面切流方案无法落地。

可接受：明确现有渐进路由方案不适用，先评估客户端升级等可控迁移条件。

明确错误：先删旧服务再验证新只读路径，以为数据自然兼容。

依据候选：拦截条件不存在时不能假装门面已控制流量，需要可执行替代方案。

反例：反例：客户端直连硬编码且无法拦截，旧源代码不可修改；原门面切流方案无法落地。 因此“先删旧服务再验证新只读路径，以为数据自然兼容。”不成立。

来源：[strangler](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10; response-sha256:e06f64b415f808e81e356a76d8caf41fb92728cb747ef4b42f3aac5617a90792；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：渐进迁移依赖可拦截路由与新旧共存；要处理共同数据/依赖的兼容，不以切流量假定旧写入已停止。门面自身可能成为单点或瓶颈；不能拦截请求时此模式可能不适用。渐进方案需比较临时成本及迁移风险，不承诺自动零停机。

本判断短引定位：system can't be intercepted

变化依据：由“旧订单服务需持续可用；可以按路径拦截，计划只迁移只读查询，写入仍由旧服务负责且新读兼容旧格式。”变为“客户端直连硬编码且无法拦截，旧源代码不可修改；原门面切流方案无法落地。”，故“用可控门面逐步切只读路径并验证回退，保旧写入入口。”改为“明确现有渐进路由方案不适用，先评估客户端升级等可控迁移条件。”。

仅改名反例：新旧入口同时在线（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：渐进切换依赖新旧共存和资源兼容，旧职责未迁移时不能提前删除。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## architecture.evolution-2 — 切流量不能停止旧写入

状态：pending_human_review；技术背景：architecture-evidence-v1；档位：进阶

**原题**

新旧服务共存，新版想立即把amount整数分改成浮点元；旧后台任务仍写整数分，回退需读旧数据。

可接受：先设计共存读写兼容和转换验证，等旧写者退役证据齐全后再移除旧表示。

明确错误：HTTP已全切新服务就可立刻破坏旧字段且无需回退检查。

依据候选：后台写者仍存活，入口流量并不能证明共同数据的旧依赖已消失。

反例：反例：新旧服务共存，新版想立即把amount整数分改成浮点元；旧后台任务仍写整数分，回退需读旧数据。 因此“HTTP已全切新服务就可立刻破坏旧字段且无需回退检查。”不成立。

来源：[strangler](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10; response-sha256:e06f64b415f808e81e356a76d8caf41fb92728cb747ef4b42f3aac5617a90792；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：渐进迁移依赖可拦截路由与新旧共存；要处理共同数据/依赖的兼容，不以切流量假定旧写入已停止。门面自身可能成为单点或瓶颈；不能拦截请求时此模式可能不适用。渐进方案需比较临时成本及迁移风险，不承诺自动零停机。

本判断短引定位：both systems can access these resources

**实质变式候选**

旧写者全部停用且排空已确认，兼容读和备份验证完成；剩余旧字段只为过期客户端提供读适配。

可接受：评估保适配器的期限与成本，按已确认客户端迁移计划逐步移除。

明确错误：HTTP已全切新服务就可立刻破坏旧字段且无需回退检查。

依据候选：移除风险已收窄到明确读依赖，可基于证据推进而非无限保所有旧写逻辑。

反例：反例：旧写者全部停用且排空已确认，兼容读和备份验证完成；剩余旧字段只为过期客户端提供读适配。 因此“HTTP已全切新服务就可立刻破坏旧字段且无需回退检查。”不成立。

来源：[strangler](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10; response-sha256:e06f64b415f808e81e356a76d8caf41fb92728cb747ef4b42f3aac5617a90792；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：渐进迁移依赖可拦截路由与新旧共存；要处理共同数据/依赖的兼容，不以切流量假定旧写入已停止。门面自身可能成为单点或瓶颈；不能拦截请求时此模式可能不适用。渐进方案需比较临时成本及迁移风险，不承诺自动零停机。

本判断短引定位：both systems can access these resources

变化依据：由“新旧服务共存，新版想立即把amount整数分改成浮点元；旧后台任务仍写整数分，回退需读旧数据。”变为“旧写者全部停用且排空已确认，兼容读和备份验证完成；剩余旧字段只为过期客户端提供读适配。”，故“先设计共存读写兼容和转换验证，等旧写者退役证据齐全后再移除旧表示。”改为“评估保适配器的期限与成本，按已确认客户端迁移计划逐步移除。”。

仅改名反例：切流量不能停止旧写入（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：后台写者仍存活，入口流量并不能证明共同数据的旧依赖已消失。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## architecture.evolution-3 — 门面成了单点

状态：pending_human_review；技术背景：architecture-evidence-v1；档位：综合

**原题**

新旧业务都经唯一门面实例；实例故障时两边均不可达，内部服务健康；跨系统语义转换也在该实例。

可接受：比较门面冗余/降级与适配职责分离，验证故障范围及新旧调用，不能只扩业务实例。

明确错误：新业务已有三副本就证明整个迁移入口无单点。

依据候选：共同入口失效会跨越新旧业务，内部副本数不能证明入口可用。

反例：反例：新旧业务都经唯一门面实例；实例故障时两边均不可达，内部服务健康；跨系统语义转换也在该实例。 因此“新业务已有三副本就证明整个迁移入口无单点。”不成立。

来源：[strangler](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10; response-sha256:e06f64b415f808e81e356a76d8caf41fb92728cb747ef4b42f3aac5617a90792；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：渐进迁移依赖可拦截路由与新旧共存；要处理共同数据/依赖的兼容，不以切流量假定旧写入已停止。门面自身可能成为单点或瓶颈；不能拦截请求时此模式可能不适用。渐进方案需比较临时成本及迁移风险，不承诺自动零停机。

本判断短引定位：single point of failure

**实质变式候选**

入口冗余切换已验证，但旧系统的取消语义被直接映射为新系统永久删除，隔离重放显示误删。

可接受：保已证入口冗余，修语义适配与恢复验证后再切该功能，不把误删当容量问题。

明确错误：新业务已有三副本就证明整个迁移入口无单点。

依据候选：可用性单点修好后仍需核跨系统含义，新的数据风险要求不同修复。

反例：反例：入口冗余切换已验证，但旧系统的取消语义被直接映射为新系统永久删除，隔离重放显示误删。 因此“新业务已有三副本就证明整个迁移入口无单点。”不成立。

来源：[strangler](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10; response-sha256:e06f64b415f808e81e356a76d8caf41fb92728cb747ef4b42f3aac5617a90792；Microsoft Azure Architecture Center, Strangler Fig / Issues and considerations / When to use; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：渐进迁移依赖可拦截路由与新旧共存；要处理共同数据/依赖的兼容，不以切流量假定旧写入已停止。门面自身可能成为单点或瓶颈；不能拦截请求时此模式可能不适用。渐进方案需比较临时成本及迁移风险，不承诺自动零停机。

本判断短引定位：translates requests between the two systems

变化依据：由“新旧业务都经唯一门面实例；实例故障时两边均不可达，内部服务健康；跨系统语义转换也在该实例。”变为“入口冗余切换已验证，但旧系统的取消语义被直接映射为新系统永久删除，隔离重放显示误删。”，故“比较门面冗余/降级与适配职责分离，验证故障范围及新旧调用，不能只扩业务实例。”改为“保已证入口冗余，修语义适配与恢复验证后再切该功能，不把误删当容量问题。”。

仅改名反例：门面成了单点（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：共同入口失效会跨越新旧业务，内部副本数不能证明入口可用。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## team.review-1 — AI说安全但没看差异

状态：pending_human_review；技术背景：team-evidence-v1；档位：基础

**原题**

AI总结称只改按钮；真实diff还移除了保存API的owner条件，只有截图测试，没有跨账号检查。

可接受：追踪API调用与权限差异，构造跨账号拒绝测试，不能按总结批准。

明确错误：AI总结和截图都说正常就不看服务端差异。

依据候选：摘要遗漏可达权限变更，审查应覆盖实际差异与系统上下文。

反例：反例：AI总结称只改按钮；真实diff还移除了保存API的owner条件，只有截图测试，没有跨账号检查。 因此“AI总结和截图都说正常就不看服务端差异。”不成立。

来源：[review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10; response-sha256:5946a2fa713dbafed9a2846e187be7705e3f3240c2b925f13d45530791c0e4af；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按变更风险核真实代码及上下文，测试应能在对应缺陷存在时失败；测试本身也需审查。局部差异、摘要或绿色数量不能替代真实调用、需求和边界验证；范围合理不要求为每次小改重测全世界。

本判断短引定位：look at the whole file

**实质变式候选**

diff已证明owner条件未变且跨账号拒绝通过；按钮键盘事件重复提交同请求，现测试只覆盖鼠标。

可接受：保已核权限结论，增加键盘重复提交的真实回归，不再凭摘要泛称安全。

明确错误：AI总结和截图都说正常就不看服务端差异。

依据候选：新可达路径与既有鼠标测试不同，应针对实际证据扩大检查。

反例：反例：diff已证明owner条件未变且跨账号拒绝通过；按钮键盘事件重复提交同请求，现测试只覆盖鼠标。 因此“AI总结和截图都说正常就不看服务端差异。”不成立。

来源：[review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10; response-sha256:5946a2fa713dbafed9a2846e187be7705e3f3240c2b925f13d45530791c0e4af；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按变更风险核真实代码及上下文，测试应能在对应缺陷存在时失败；测试本身也需审查。局部差异、摘要或绿色数量不能替代真实调用、需求和边界验证；范围合理不要求为每次小改重测全世界。

本判断短引定位：Will the tests actually fail when the code is broken?

变化依据：由“AI总结称只改按钮；真实diff还移除了保存API的owner条件，只有截图测试，没有跨账号检查。”变为“diff已证明owner条件未变且跨账号拒绝通过；按钮键盘事件重复提交同请求，现测试只覆盖鼠标。”，故“追踪API调用与权限差异，构造跨账号拒绝测试，不能按总结批准。”改为“保已核权限结论，增加键盘重复提交的真实回归，不再凭摘要泛称安全。”。

仅改名反例：AI说安全但没看差异（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：摘要遗漏可达权限变更，审查应覆盖实际差异与系统上下文。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## team.review-2 — 绿色测试不一定拦回归

状态：pending_human_review；技术背景：team-evidence-v1；档位：进阶

**原题**

修复竞态的测试断言最终值，但旧代码在故障屏障下也通过；作者以100%绿称竞态已验收。

可接受：先让旧缺陷确定出现并使同一核心断言失败，再核新修复通过。

明确错误：只增加运行次数和绿色数量即可证明测试覆盖该竞态。

依据候选：不能在旧错误下失败的测试未证明防回归，应核真实时序与断言。

反例：反例：修复竞态的测试断言最终值，但旧代码在故障屏障下也通过；作者以100%绿称竞态已验收。 因此“只增加运行次数和绿色数量即可证明测试覆盖该竞态。”不成立。

来源：[review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10; response-sha256:5946a2fa713dbafed9a2846e187be7705e3f3240c2b925f13d45530791c0e4af；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按变更风险核真实代码及上下文，测试应能在对应缺陷存在时失败；测试本身也需审查。局部差异、摘要或绿色数量不能替代真实调用、需求和边界验证；范围合理不要求为每次小改重测全世界。

本判断短引定位：Will the tests actually fail when the code is broken?

**实质变式候选**

旧代码已确定失败、新代码通过；新增错误分支未保用户输入，原竞态测试不执行该分支。

可接受：保竞态证据，另按失败恢复契约覆盖新增分支，不篡改原断言。

明确错误：只增加运行次数和绿色数量即可证明测试覆盖该竞态。

依据候选：一条充分测试不能外推其他可达路径，审查需要对应风险证据。

反例：反例：旧代码已确定失败、新代码通过；新增错误分支未保用户输入，原竞态测试不执行该分支。 因此“只增加运行次数和绿色数量即可证明测试覆盖该竞态。”不成立。

来源：[review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10; response-sha256:5946a2fa713dbafed9a2846e187be7705e3f3240c2b925f13d45530791c0e4af；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按变更风险核真实代码及上下文，测试应能在对应缺陷存在时失败；测试本身也需审查。局部差异、摘要或绿色数量不能替代真实调用、需求和边界验证；范围合理不要求为每次小改重测全世界。

本判断短引定位：Will the tests actually fail when the code is broken?

变化依据：由“修复竞态的测试断言最终值，但旧代码在故障屏障下也通过；作者以100%绿称竞态已验收。”变为“旧代码已确定失败、新代码通过；新增错误分支未保用户输入，原竞态测试不执行该分支。”，故“先让旧缺陷确定出现并使同一核心断言失败，再核新修复通过。”改为“保竞态证据，另按失败恢复契约覆盖新增分支，不篡改原断言。”。

仅改名反例：绿色测试不一定拦回归（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：不能在旧错误下失败的测试未证明防回归，应核真实时序与断言。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## team.review-3 — 两份AI赞同不等于人工核验

状态：pending_human_review；技术背景：team-evidence-v1；档位：综合

**原题**

两次Copilot意见一致称迁移安全，未打开实际迁移脚本；脚本可能覆盖旧字段且无旧数据恢复演练。

可接受：核实际脚本与旧数据路径，补恢复边界验证并请求人工审查，不把AI一致当签核。

明确错误：两份AI赞同可以填人工批准并省略数据验证。

依据候选：AI可漏报或误判，真实数据迁移必须用实际差异和测试核查。

反例：反例：两次Copilot意见一致称迁移安全，未打开实际迁移脚本；脚本可能覆盖旧字段且无旧数据恢复演练。 因此“两份AI赞同可以填人工批准并省略数据验证。”不成立。

来源：[copilot](https://docs.github.com/en/copilot/concepts/agents/code-review)；GitHub Docs, About GitHub Copilot code review / Validating Copilot code reviews; snapshot 2026-09-10; response-sha256:0a7e85bef65c8a875edf074384235befff3eeb888299ff2fa5b9bea70ecbc286；GitHub Docs, About GitHub Copilot code review / Validating Copilot code reviews; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：Copilot可能漏报或误报，需核验反馈并辅以人工审查。AI意见仅为检查线索，不以两份AI赞同冒充人类签核或实际验证；具体缺陷是否成立应看真实代码与证据。

本判断短引定位：not guaranteed to spot all problems or issues

来源：[review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10; response-sha256:5946a2fa713dbafed9a2846e187be7705e3f3240c2b925f13d45530791c0e4af；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按变更风险核真实代码及上下文，测试应能在对应缺陷存在时失败；测试本身也需审查。局部差异、摘要或绿色数量不能替代真实调用、需求和边界验证；范围合理不要求为每次小改重测全世界。

本判断短引定位：look at the whole file

**实质变式候选**

人工已核本版本迁移且旧数据验证通过；后续提交改了转换规则，只有先前AI评论和旧报告。

可接受：保旧版本证据，对新差异及受影响恢复路径重新核验，不沿用旧签核覆盖新代码。

明确错误：两份AI赞同可以填人工批准并省略数据验证。

依据候选：审查证据绑定真实版本，新增变更不能由先前评论自动验证。

反例：反例：人工已核本版本迁移且旧数据验证通过；后续提交改了转换规则，只有先前AI评论和旧报告。 因此“两份AI赞同可以填人工批准并省略数据验证。”不成立。

来源：[copilot](https://docs.github.com/en/copilot/concepts/agents/code-review)；GitHub Docs, About GitHub Copilot code review / Validating Copilot code reviews; snapshot 2026-09-10; response-sha256:0a7e85bef65c8a875edf074384235befff3eeb888299ff2fa5b9bea70ecbc286；GitHub Docs, About GitHub Copilot code review / Validating Copilot code reviews; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：Copilot可能漏报或误报，需核验反馈并辅以人工审查。AI意见仅为检查线索，不以两份AI赞同冒充人类签核或实际验证；具体缺陷是否成立应看真实代码与证据。

本判断短引定位：Supplement Copilot's feedback with a human review.

来源：[review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10; response-sha256:5946a2fa713dbafed9a2846e187be7705e3f3240c2b925f13d45530791c0e4af；Google Engineering Practices, What to look for / Tests / Context; snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：按变更风险核真实代码及上下文，测试应能在对应缺陷存在时失败；测试本身也需审查。局部差异、摘要或绿色数量不能替代真实调用、需求和边界验证；范围合理不要求为每次小改重测全世界。

本判断短引定位：look at the whole file

变化依据：由“两次Copilot意见一致称迁移安全，未打开实际迁移脚本；脚本可能覆盖旧字段且无旧数据恢复演练。”变为“人工已核本版本迁移且旧数据验证通过；后续提交改了转换规则，只有先前AI评论和旧报告。”，故“核实际脚本与旧数据路径，补恢复边界验证并请求人工审查，不把AI一致当签核。”改为“保旧版本证据，对新差异及受影响恢复路径重新核验，不沿用旧签核覆盖新代码。”。

仅改名反例：两份AI赞同不等于人工核验（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：AI可漏报或误判，真实数据迁移必须用实际差异和测试核查。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## team.handoff-1 — 交接只有一句修好了

状态：pending_human_review；技术背景：team-evidence-v1；档位：基础

**原题**

事故刚缓解；交接只写“修好了”，无当前版本、影响范围和验证结果，接班者不知是否还有写入积压。

可接受：记录当前版本、已观察影响、缓解动作和待核积压，给可执行下一步。

明确错误：把修好了转发出去即可证明事故根因与恢复都完成。

依据候选：可恢复交接需要事实与动作，缓解不等于全部恢复或原因已证实。

反例：反例：事故刚缓解；交接只写“修好了”，无当前版本、影响范围和验证结果，接班者不知是否还有写入积压。 因此“把修好了转发出去即可证明事故根因与恢复都完成。”不成立。

来源：[postmortem](https://sre.google/sre-book/postmortem-culture/)；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy; response-sha256:885916e3c46dfb2cf3a506435f9df60ca1bf3e491e521725705f7202ac12eb49；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy。规范摘要（AI中文改写，待人工核验，非逐字引句）：复盘记录影响、缓解、原因及预防跟进，区分已观测事实与待证假设；无责复盘关注系统贡献因素，不归咎个人。文档形成及修复动作完成不自动证明复发风险已消除，后续需检查措施是否有效。

本判断短引定位：its impact, the actions taken to mitigate or resolve it

**实质变式候选**

版本与影响已写明，积压排空也确认；但预防措施未实施且原因仍有两种假设。

可接受：保已完成恢复，明确待证原因与预防跟进，不把未实施措施标已验证。

明确错误：把修好了转发出去即可证明事故根因与恢复都完成。

依据候选：新材料支持恢复但不足以证明复发预防，状态应分开记录。

反例：反例：版本与影响已写明，积压排空也确认；但预防措施未实施且原因仍有两种假设。 因此“把修好了转发出去即可证明事故根因与恢复都完成。”不成立。

来源：[postmortem](https://sre.google/sre-book/postmortem-culture/)；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy; response-sha256:885916e3c46dfb2cf3a506435f9df60ca1bf3e491e521725705f7202ac12eb49；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy。规范摘要（AI中文改写，待人工核验，非逐字引句）：复盘记录影响、缓解、原因及预防跟进，区分已观测事实与待证假设；无责复盘关注系统贡献因素，不归咎个人。文档形成及修复动作完成不自动证明复发风险已消除，后续需检查措施是否有效。

本判断短引定位：follow-up actions to prevent the incident from recurring

变化依据：由“事故刚缓解；交接只写“修好了”，无当前版本、影响范围和验证结果，接班者不知是否还有写入积压。”变为“版本与影响已写明，积压排空也确认；但预防措施未实施且原因仍有两种假设。”，故“记录当前版本、已观察影响、缓解动作和待核积压，给可执行下一步。”改为“保已完成恢复，明确待证原因与预防跟进，不把未实施措施标已验证。”。

仅改名反例：交接只有一句修好了（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：可恢复交接需要事实与动作，缓解不等于全部恢复或原因已证实。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## team.handoff-2 — 把时间相关当原因

状态：pending_human_review；技术背景：team-evidence-v1；档位：进阶

**原题**

事故发生在发布后，复盘直接写工程师粗心导致；没有请求轨迹与配置差异，回退后恢复但仍可能是外依赖同期恢复。

可接受：保时间线，分别核发布与外依赖假设，记录贡献因素而不归咎个人。

明确错误：回退后恢复就足以证明某个人是唯一根因。

依据候选：先后关系不足以排除其他原因，无责复盘应查系统贡献因素。

反例：反例：事故发生在发布后，复盘直接写工程师粗心导致；没有请求轨迹与配置差异，回退后恢复但仍可能是外依赖同期恢复。 因此“回退后恢复就足以证明某个人是唯一根因。”不成立。

来源：[postmortem](https://sre.google/sre-book/postmortem-culture/)；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy; response-sha256:885916e3c46dfb2cf3a506435f9df60ca1bf3e491e521725705f7202ac12eb49；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy。规范摘要（AI中文改写，待人工核验，非逐字引句）：复盘记录影响、缓解、原因及预防跟进，区分已观测事实与待证假设；无责复盘关注系统贡献因素，不归咎个人。文档形成及修复动作完成不自动证明复发风险已消除，后续需检查措施是否有效。

本判断短引定位：identifying the contributing causes

**实质变式候选**

重放已确认配置差异触发故障；记录仍只要求当事人下次小心，没有预防检查或验证。

可接受：保已证原因，安排可检查的配置保护与有效性验证，而非仅提醒个人。

明确错误：回退后恢复就足以证明某个人是唯一根因。

依据候选：原因明确后应形成系统预防动作，不能用个人承诺替代验证。

反例：反例：重放已确认配置差异触发故障；记录仍只要求当事人下次小心，没有预防检查或验证。 因此“回退后恢复就足以证明某个人是唯一根因。”不成立。

来源：[postmortem](https://sre.google/sre-book/postmortem-culture/)；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy; response-sha256:885916e3c46dfb2cf3a506435f9df60ca1bf3e491e521725705f7202ac12eb49；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy。规范摘要（AI中文改写，待人工核验，非逐字引句）：复盘记录影响、缓解、原因及预防跟进，区分已观测事实与待证假设；无责复盘关注系统贡献因素，不归咎个人。文档形成及修复动作完成不自动证明复发风险已消除，后续需检查措施是否有效。

本判断短引定位：follow-up actions to prevent the incident from recurring

变化依据：由“事故发生在发布后，复盘直接写工程师粗心导致；没有请求轨迹与配置差异，回退后恢复但仍可能是外依赖同期恢复。”变为“重放已确认配置差异触发故障；记录仍只要求当事人下次小心，没有预防检查或验证。”，故“保时间线，分别核发布与外依赖假设，记录贡献因素而不归咎个人。”改为“保已证原因，安排可检查的配置保护与有效性验证，而非仅提醒个人。”。

仅改名反例：把时间相关当原因（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：先后关系不足以排除其他原因，无责复盘应查系统贡献因素。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## team.handoff-3 — 多团队恢复记录冲突

状态：pending_human_review；技术背景：team-evidence-v1；档位：综合

**原题**

支付团队写10:05全恢复，队列团队10:15仍回放旧失败订单；没有统一订单范围与时区，交接宣称无损。

可接受：按统一时间与业务身份核对各自影响、回放和剩余风险，保冲突记录待证。

明确错误：选最早恢复时间删掉另一团队记录就能证明无损。

依据候选：跨团队局部恢复不能直接合成全局无损，需要一致的可追溯影响与动作证据。

反例：反例：支付团队写10:05全恢复，队列团队10:15仍回放旧失败订单；没有统一订单范围与时区，交接宣称无损。 因此“选最早恢复时间删掉另一团队记录就能证明无损。”不成立。

来源：[postmortem](https://sre.google/sre-book/postmortem-culture/)；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy; response-sha256:885916e3c46dfb2cf3a506435f9df60ca1bf3e491e521725705f7202ac12eb49；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy。规范摘要（AI中文改写，待人工核验，非逐字引句）：复盘记录影响、缓解、原因及预防跟进，区分已观测事实与待证假设；无责复盘关注系统贡献因素，不归咎个人。文档形成及修复动作完成不自动证明复发风险已消除，后续需检查措施是否有效。

本判断短引定位：its impact, the actions taken to mitigate or resolve it

**实质变式候选**

统一记录已核只剩10个订单待人工授权补偿；防重修复已部署但未测试迟到重放。

可接受：明确剩余补偿和授权状态，保已核范围，新增迟到重放验证后再称措施有效。

明确错误：选最早恢复时间删掉另一团队记录就能证明无损。

依据候选：对账缩小了未知范围，部署事实仍不证明预防动作在剩余路径有效。

反例：反例：统一记录已核只剩10个订单待人工授权补偿；防重修复已部署但未测试迟到重放。 因此“选最早恢复时间删掉另一团队记录就能证明无损。”不成立。

来源：[postmortem](https://sre.google/sre-book/postmortem-culture/)；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy; response-sha256:885916e3c46dfb2cf3a506435f9df60ca1bf3e491e521725705f7202ac12eb49；Google SRE book (2016), Postmortem Culture / Google’s Postmortem Philosophy。规范摘要（AI中文改写，待人工核验，非逐字引句）：复盘记录影响、缓解、原因及预防跟进，区分已观测事实与待证假设；无责复盘关注系统贡献因素，不归咎个人。文档形成及修复动作完成不自动证明复发风险已消除，后续需检查措施是否有效。

本判断短引定位：follow-up actions to prevent the incident from recurring

变化依据：由“支付团队写10:05全恢复，队列团队10:15仍回放旧失败订单；没有统一订单范围与时区，交接宣称无损。”变为“统一记录已核只剩10个订单待人工授权补偿；防重修复已部署但未测试迟到重放。”，故“按统一时间与业务身份核对各自影响、回放和剩余风险，保冲突记录待证。”改为“明确剩余补偿和授权状态，保已核范围，新增迟到重放验证后再称措施有效。”。

仅改名反例：多团队恢复记录冲突（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：跨团队局部恢复不能直接合成全局无损，需要一致的可追溯影响与动作证据。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。
