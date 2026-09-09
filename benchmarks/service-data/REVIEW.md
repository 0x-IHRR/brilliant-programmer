# 逐条人工复核待办

全部为 AI 草稿，尚无人类签核。以下便于审阅，JSON保留完整结构；此清单不自动认可标签。

## api.boundary-1 — 过期令牌与对象访问

状态：pending_human_review；技术背景：api-evidence-v1；档位：基础

**原题**

Bearer令牌已过期；订单归属尚未读取。

可接受：拒绝该认证并按无效令牌处理；不能继续访问订单。

明确错误：令牌字符串存在就查询并返回订单。

依据候选：令牌存在不代表有效；当前已确定过期，先在认证边界拒绝。

反例：反例：Bearer令牌已过期；订单归属尚未读取。 因此“令牌字符串存在就查询并返回订单。”不成立。

来源：[oauth](https://www.rfc-editor.org/rfc/rfc6750.txt)；RFC6750 (2012); response-sha256:9dc385cf4ecdd85024e5a95e447ede9230e11700bf35251906b25b37557d604b；RFC6750 (2012), §3.1。规范摘要（AI中文改写，待人工核验，非逐字引句）：无效令牌通常返回401；权限范围不足通常返回403。无认证信息时不附详细错误码。只说明Bearer边界，不证明对象归属。

本判断短引定位：expired, revoked, malformed

来源：[object](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)；OWASP API Security Top10 2023 API1; response-sha256:838060e500f0616879a90bc17077d23f9da72eb8946a53d959a46f8ed5c9249e；OWASP API Security Top10 2023 API1, How To Prevent。规范摘要（AI中文改写，待人工核验，非逐字引句）：每个使用客户端标识访问记录的功能都须核验该登录用户能否对目标记录执行该动作；随机ID不能替代授权。

本判断短引定位：logged-in user has access to perform the requested action

**实质变式候选**

令牌有效且所需scope齐全；订单属于另一个账号，没有共享授权。

可接受：在对象授权边界拒绝，不能把认证有效当归属许可。

明确错误：令牌字符串存在就查询并返回订单。

依据候选：新的证据把问题从令牌失效改为对象越权，仍不得返回对象。

反例：反例：令牌有效且所需scope齐全；订单属于另一个账号，没有共享授权。 因此“令牌字符串存在就查询并返回订单。”不成立。

来源：[oauth](https://www.rfc-editor.org/rfc/rfc6750.txt)；RFC6750 (2012); response-sha256:9dc385cf4ecdd85024e5a95e447ede9230e11700bf35251906b25b37557d604b；RFC6750 (2012), §3.1。规范摘要（AI中文改写，待人工核验，非逐字引句）：无效令牌通常返回401；权限范围不足通常返回403。无认证信息时不附详细错误码。只说明Bearer边界，不证明对象归属。

本判断短引定位：expired, revoked, malformed

来源：[object](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)；OWASP API Security Top10 2023 API1; response-sha256:838060e500f0616879a90bc17077d23f9da72eb8946a53d959a46f8ed5c9249e；OWASP API Security Top10 2023 API1, How To Prevent。规范摘要（AI中文改写，待人工核验，非逐字引句）：每个使用客户端标识访问记录的功能都须核验该登录用户能否对目标记录执行该动作；随机ID不能替代授权。

本判断短引定位：logged-in user has access to perform the requested action

变化依据：由“Bearer令牌已过期；订单归属尚未读取。”变为“令牌有效且所需scope齐全；订单属于另一个账号，没有共享授权。”，故“拒绝该认证并按无效令牌处理；不能继续访问订单。”改为“在对象授权边界拒绝，不能把认证有效当归属许可。”。

仅改名反例：过期令牌与对象访问（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：令牌存在不代表有效；当前已确定过期，先在认证边界拒绝。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## api.boundary-2 — 权限范围不是参数格式

状态：pending_human_review；技术背景：api-evidence-v1；档位：进阶

**原题**

令牌有效但只有read scope；请求修改订单，字段格式与数量均合法。

可接受：在scope授权边界拒绝写入，反馈权限不足。

明确错误：参数合法且已登录就允许写入。

依据候选：格式正确与身份有效都不能补足缺失的write权限。

反例：反例：令牌有效但只有read scope；请求修改订单，字段格式与数量均合法。 因此“参数合法且已登录就允许写入。”不成立。

来源：[oauth](https://www.rfc-editor.org/rfc/rfc6750.txt)；RFC6750 (2012); response-sha256:9dc385cf4ecdd85024e5a95e447ede9230e11700bf35251906b25b37557d604b；RFC6750 (2012), §3.1。规范摘要（AI中文改写，待人工核验，非逐字引句）：无效令牌通常返回401；权限范围不足通常返回403。无认证信息时不附详细错误码。只说明Bearer边界，不证明对象归属。

本判断短引定位：higher privileges than provided

**实质变式候选**

令牌含write scope且对象归属合法；数量=-2违反本接口明确正数业务规则。

可接受：权限校验通过后按业务约束拒绝负数量。

明确错误：参数合法且已登录就允许写入。

依据候选：权限齐全不保证业务有效，改变后的拒绝依据是已冻结的数量规则。

反例：反例：令牌含write scope且对象归属合法；数量=-2违反本接口明确正数业务规则。 因此“参数合法且已登录就允许写入。”不成立。

来源：[oauth](https://www.rfc-editor.org/rfc/rfc6750.txt)；RFC6750 (2012); response-sha256:9dc385cf4ecdd85024e5a95e447ede9230e11700bf35251906b25b37557d604b；RFC6750 (2012), §3.1。规范摘要（AI中文改写，待人工核验，非逐字引句）：无效令牌通常返回401；权限范围不足通常返回403。无认证信息时不附详细错误码。只说明Bearer边界，不证明对象归属。

本判断短引定位：higher privileges than provided

变化依据：由“令牌有效但只有read scope；请求修改订单，字段格式与数量均合法。”变为“令牌含write scope且对象归属合法；数量=-2违反本接口明确正数业务规则。”，故“在scope授权边界拒绝写入，反馈权限不足。”改为“权限校验通过后按业务约束拒绝负数量。”。

仅改名反例：权限范围不是参数格式（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：格式正确与身份有效都不能补足缺失的write权限。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## api.boundary-3 — 随机资源ID与批量授权

状态：pending_human_review；技术背景：api-evidence-v1；档位：综合

**原题**

有效令牌请求批量读取两个随机订单ID；一个属本人，另一个属他人；接口契约要求整批授权后才返回。

可接受：核对每个对象的访问权，整批拒绝且不泄露另一个订单。

明确错误：ID不可猜且有一个订单属本人，所以整批返回。

依据候选：随机标识和部分合法对象都不替代逐对象授权；整批语义由题面明确给定。

反例：反例：有效令牌请求批量读取两个随机订单ID；一个属本人，另一个属他人；接口契约要求整批授权后才返回。 因此“ID不可猜且有一个订单属本人，所以整批返回。”不成立。

来源：[object](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)；OWASP API Security Top10 2023 API1; response-sha256:838060e500f0616879a90bc17077d23f9da72eb8946a53d959a46f8ed5c9249e；OWASP API Security Top10 2023 API1, How To Prevent。规范摘要（AI中文改写，待人工核验，非逐字引句）：每个使用客户端标识访问记录的功能都须核验该登录用户能否对目标记录执行该动作；随机ID不能替代授权。

本判断短引定位：logged-in user has access to perform the requested action

**实质变式候选**

两个订单均获共享读取授权；其中一个已撤销写权限，请求从读取改为写入。

可接受：按每对象的写动作权限拒绝该批更新。

明确错误：ID不可猜且有一个订单属本人，所以整批返回。

依据候选：读取授权不能迁移成写授权，必须用当前动作核对每个对象。

反例：反例：两个订单均获共享读取授权；其中一个已撤销写权限，请求从读取改为写入。 因此“ID不可猜且有一个订单属本人，所以整批返回。”不成立。

来源：[object](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)；OWASP API Security Top10 2023 API1; response-sha256:838060e500f0616879a90bc17077d23f9da72eb8946a53d959a46f8ed5c9249e；OWASP API Security Top10 2023 API1, How To Prevent。规范摘要（AI中文改写，待人工核验，非逐字引句）：每个使用客户端标识访问记录的功能都须核验该登录用户能否对目标记录执行该动作；随机ID不能替代授权。

本判断短引定位：logged-in user has access to perform the requested action

变化依据：由“有效令牌请求批量读取两个随机订单ID；一个属本人，另一个属他人；接口契约要求整批授权后才返回。”变为“两个订单均获共享读取授权；其中一个已撤销写权限，请求从读取改为写入。”，故“核对每个对象的访问权，整批拒绝且不泄露另一个订单。”改为“按每对象的写动作权限拒绝该批更新。”。

仅改名反例：随机资源ID与批量授权（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：随机标识和部分合法对象都不替代逐对象授权；整批语义由题面明确给定。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## api.idempotency-1 — 断线后的同键请求

状态：pending_human_review；技术背景：api-evidence-v1；档位：基础

**原题**

Stripe POST已开始执行并成功创建对象，但客户端响应丢失；原幂等键和相同参数仍保留且键未清理。

可接受：用原键和相同参数查询式重放，取得保存的结果。

明确错误：生成新键重发同一创建请求。

依据候选：在给定保留期和参数一致前提下，同键复用原结果；新键会失去该次防重关联。

反例：反例：Stripe POST已开始执行并成功创建对象，但客户端响应丢失；原幂等键和相同参数仍保留且键未清理。 因此“生成新键重发同一创建请求。”不成立。

来源：[stripe](https://docs.stripe.com/api/idempotent_requests)；Stripe API; response-sha256:0e75cda4483151c8e3259f16b473e3f0cd9418161cfce833cf7a5bf4316ef3d2；Stripe API, Idempotent requests, read snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同幂等键保存首次已开始执行请求的状态和正文，含500；参数不同会报错。参数校验或并发执行冲突未开始执行时不保存该幂等结果，可重试。键至少24小时后可清理，清理后重用会生成新请求，不能保证永久防重。

本判断短引定位：saving the resulting status code and body

**实质变式候选**

原请求已保存500结果，键仍保留，参数相同。

可接受：保留原请求身份并处理该已保存失败，不把换键当安全重试。

明确错误：生成新键重发同一创建请求。

依据候选：同键也会重放保存的500，未知副作用不能靠新键自动排除。

反例：反例：原请求已保存500结果，键仍保留，参数相同。 因此“生成新键重发同一创建请求。”不成立。

来源：[stripe](https://docs.stripe.com/api/idempotent_requests)；Stripe API; response-sha256:0e75cda4483151c8e3259f16b473e3f0cd9418161cfce833cf7a5bf4316ef3d2；Stripe API, Idempotent requests, read snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同幂等键保存首次已开始执行请求的状态和正文，含500；参数不同会报错。参数校验或并发执行冲突未开始执行时不保存该幂等结果，可重试。键至少24小时后可清理，清理后重用会生成新请求，不能保证永久防重。

本判断短引定位：saving the resulting status code and body

变化依据：由“Stripe POST已开始执行并成功创建对象，但客户端响应丢失；原幂等键和相同参数仍保留且键未清理。”变为“原请求已保存500结果，键仍保留，参数相同。”，故“用原键和相同参数查询式重放，取得保存的结果。”改为“保留原请求身份并处理该已保存失败，不把换键当安全重试。”。

仅改名反例：断线后的同键请求（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：在给定保留期和参数一致前提下，同键复用原结果；新键会失去该次防重关联。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## api.idempotency-2 — 并发冲突是否保存结果

状态：pending_human_review；技术背景：api-evidence-v1；档位：进阶

**原题**

同键请求仍在执行；第二请求因并发冲突未开始端点执行，参数一致。

可接受：等待首请求结算后用同键重试；不能把冲突当成已保存业务结果。

明确错误：冲突证明创建失败，立即换键再创建。

依据候选：执行前冲突不保存幂等结果，也不证明另一在途请求没有执行。

反例：反例：同键请求仍在执行；第二请求因并发冲突未开始端点执行，参数一致。 因此“冲突证明创建失败，立即换键再创建。”不成立。

来源：[stripe](https://docs.stripe.com/api/idempotent_requests)；Stripe API; response-sha256:0e75cda4483151c8e3259f16b473e3f0cd9418161cfce833cf7a5bf4316ef3d2；Stripe API, Idempotent requests, read snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同幂等键保存首次已开始执行请求的状态和正文，含500；参数不同会报错。参数校验或并发执行冲突未开始执行时不保存该幂等结果，可重试。键至少24小时后可清理，清理后重用会生成新请求，不能保证永久防重。

本判断短引定位：execution of an endpoint begins

**实质变式候选**

原请求已经成功，重放使用相同键但金额被改动。

可接受：保留原成功记录，拒绝把不同参数塞进原幂等身份；新业务需明确新请求。

明确错误：冲突证明创建失败，立即换键再创建。

依据候选：参数不一致与执行前冲突不同，不能用重试机制改写旧操作含义。

反例：反例：原请求已经成功，重放使用相同键但金额被改动。 因此“冲突证明创建失败，立即换键再创建。”不成立。

来源：[stripe](https://docs.stripe.com/api/idempotent_requests)；Stripe API; response-sha256:0e75cda4483151c8e3259f16b473e3f0cd9418161cfce833cf7a5bf4316ef3d2；Stripe API, Idempotent requests, read snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同幂等键保存首次已开始执行请求的状态和正文，含500；参数不同会报错。参数校验或并发执行冲突未开始执行时不保存该幂等结果，可重试。键至少24小时后可清理，清理后重用会生成新请求，不能保证永久防重。

本判断短引定位：compares incoming parameters

变化依据：由“同键请求仍在执行；第二请求因并发冲突未开始端点执行，参数一致。”变为“原请求已经成功，重放使用相同键但金额被改动。”，故“等待首请求结算后用同键重试；不能把冲突当成已保存业务结果。”改为“保留原成功记录，拒绝把不同参数塞进原幂等身份；新业务需明确新请求。”。

仅改名反例：并发冲突是否保存结果（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：执行前冲突不保存幂等结果，也不证明另一在途请求没有执行。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## api.idempotency-3 — 幂等键清理后的恢复

状态：pending_human_review；技术背景：api-evidence-v1；档位：综合

**原题**

原支付调用响应未知；48小时后确认幂等键已被清理；订单本地仍pending且没有支付结果核对。

可接受：先按业务订单核对外部结果和持久记录，不能直接复用已清理键认定安全。

明确错误：只要字符串相同，48小时后重发也永久只扣一次。

依据候选：已清理键的重用会产生新请求；本地pending不证明外部未执行，需先补结果。

反例：反例：原支付调用响应未知；48小时后确认幂等键已被清理；订单本地仍pending且没有支付结果核对。 因此“只要字符串相同，48小时后重发也永久只扣一次。”不成立。

来源：[stripe](https://docs.stripe.com/api/idempotent_requests)；Stripe API; response-sha256:0e75cda4483151c8e3259f16b473e3f0cd9418161cfce833cf7a5bf4316ef3d2；Stripe API, Idempotent requests, read snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同幂等键保存首次已开始执行请求的状态和正文，含500；参数不同会报错。参数校验或并发执行冲突未开始执行时不保存该幂等结果，可重试。键至少24小时后可清理，清理后重用会生成新请求，不能保证永久防重。

本判断短引定位：after the original is pruned

**实质变式候选**

已根据业务订单取得外部明确未执行证明，且本地防重事务已受理一次主动新请求。

可接受：按新业务请求执行并持久记录其新身份与恢复结果。

明确错误：只要字符串相同，48小时后重发也永久只扣一次。

依据候选：补齐外部未执行及本地受理证据后可明确新开，不能把该结论用于此前未知状态。

反例：反例：已根据业务订单取得外部明确未执行证明，且本地防重事务已受理一次主动新请求。 因此“只要字符串相同，48小时后重发也永久只扣一次。”不成立。

来源：[stripe](https://docs.stripe.com/api/idempotent_requests)；Stripe API; response-sha256:0e75cda4483151c8e3259f16b473e3f0cd9418161cfce833cf7a5bf4316ef3d2；Stripe API, Idempotent requests, read snapshot 2026-09-10。规范摘要（AI中文改写，待人工核验，非逐字引句）：同幂等键保存首次已开始执行请求的状态和正文，含500；参数不同会报错。参数校验或并发执行冲突未开始执行时不保存该幂等结果，可重试。键至少24小时后可清理，清理后重用会生成新请求，不能保证永久防重。

本判断短引定位：after the original is pruned

变化依据：由“原支付调用响应未知；48小时后确认幂等键已被清理；订单本地仍pending且没有支付结果核对。”变为“已根据业务订单取得外部明确未执行证明，且本地防重事务已受理一次主动新请求。”，故“先按业务订单核对外部结果和持久记录，不能直接复用已清理键认定安全。”改为“按新业务请求执行并持久记录其新身份与恢复结果。”。

仅改名反例：幂等键清理后的恢复（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：已清理键的重用会产生新请求；本地pending不证明外部未执行，需先补结果。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## data.integrity-1 — 并发预查没有占住唯一名额

状态：pending_human_review；技术背景：data-evidence-v1；档位：基础

**原题**

两个事务均预查同一非空订单号不存在；尚无唯一约束，两者随后插入。

可接受：用订单号唯一约束守住不变量，并处理冲突结果。

明确错误：只要两次预查都返回空，两个插入就不会重复。

依据候选：预查与写入间存在并发窗口，数据库唯一约束才对最终列组合施加限制。

反例：反例：两个事务均预查同一非空订单号不存在；尚无唯一约束，两者随后插入。 因此“只要两次预查都返回空，两个插入就不会重复。”不成立。

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：unique across the whole table

**实质变式候选**

数据库已有订单号唯一约束；第二次插入被冲突拒绝，第一条已提交。

可接受：保留第一条，读取并核对它是否是同一业务，不把冲突改成无约束插入。

明确错误：只要两次预查都返回空，两个插入就不会重复。

依据候选：改变后的库已拒绝重复，恢复应核对已存身份而非绕开约束。

反例：反例：数据库已有订单号唯一约束；第二次插入被冲突拒绝，第一条已提交。 因此“只要两次预查都返回空，两个插入就不会重复。”不成立。

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：unique across the whole table

变化依据：由“两个事务均预查同一非空订单号不存在；尚无唯一约束，两者随后插入。”变为“数据库已有订单号唯一约束；第二次插入被冲突拒绝，第一条已提交。”，故“用订单号唯一约束守住不变量，并处理冲突结果。”改为“保留第一条，读取并核对它是否是同一业务，不把冲突改成无约束插入。”。

仅改名反例：并发预查没有占住唯一名额（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：预查与写入间存在并发窗口，数据库唯一约束才对最终列组合施加限制。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## data.integrity-2 — NULL既影响唯一也影响必填

状态：pending_human_review；技术背景：data-evidence-v1；档位：进阶

**原题**

表有UNIQUE(code)及CHECK(price>0)，没有NOT NULL；第二条code=NULL、price=NULL被接收。

可接受：解释默认NULL互异且CHECK遇NULL可满足；按必填需求补NOT NULL等约束。

明确错误：唯一加CHECK已保证非空，所以数据库肯定损坏。

依据候选：这两类约束不自动实现必填；必须把业务不变量明确写成适当约束。

反例：反例：表有UNIQUE(code)及CHECK(price>0)，没有NOT NULL；第二条code=NULL、price=NULL被接收。 因此“唯一加CHECK已保证非空，所以数据库肯定损坏。”不成立。

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：true or the null value

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：null values are not considered equal

**实质变式候选**

code允许空但最多一条空；已使用NULLS NOT DISTINCT，price仍要求必填。

可接受：保留code空值唯一语义，并独立给price补NOT NULL。

明确错误：唯一加CHECK已保证非空，所以数据库肯定损坏。

依据候选：空值可选与数值必填是两个不同不变量，不能一概禁止所有NULL。

反例：反例：code允许空但最多一条空；已使用NULLS NOT DISTINCT，price仍要求必填。 因此“唯一加CHECK已保证非空，所以数据库肯定损坏。”不成立。

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：true or the null value

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：null values are not considered equal

变化依据：由“表有UNIQUE(code)及CHECK(price>0)，没有NOT NULL；第二条code=NULL、price=NULL被接收。”变为“code允许空但最多一条空；已使用NULLS NOT DISTINCT，price仍要求必填。”，故“解释默认NULL互异且CHECK遇NULL可满足；按必填需求补NOT NULL等约束。”改为“保留code空值唯一语义，并独立给price补NOT NULL。”。

仅改名反例：NULL既影响唯一也影响必填（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：这两类约束不自动实现必填；必须把业务不变量明确写成适当约束。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## data.integrity-3 — 跨行规则与恢复一致性

状态：pending_human_review；技术背景：data-evidence-v1；档位：综合

**原题**

应用把订单号全表不重复写成调用查其他行函数的CHECK；后续别行更新及备份恢复均需保持规则。

可接受：以真正跨行唯一约束表达订单号规则，迁移前先核对并处理已有重复。

明确错误：CHECK调用能查其他行，就能永久替代唯一约束。

依据候选：PostgreSQL不支持用此类CHECK持续保证跨行规则，迁移仍需处理已有数据。

反例：反例：应用把订单号全表不重复写成调用查其他行函数的CHECK；后续别行更新及备份恢复均需保持规则。 因此“CHECK调用能查其他行，就能永久替代唯一约束。”不成立。

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：new or updated row being checked

**实质变式候选**

业务规则改为同资源预订时间不得重叠；订单号唯一无法表达，且边界相接允许。

可接受：按时间区间与资源设计排斥约束或等价串行边界，并明确边界语义后验证。

明确错误：CHECK调用能查其他行，就能永久替代唯一约束。

依据候选：新的不变量是区间重叠而非相等，唯一约束不足；不能照搬原方案。

反例：反例：业务规则改为同资源预订时间不得重叠；订单号唯一无法表达，且边界相接允许。 因此“CHECK调用能查其他行，就能永久替代唯一约束。”不成立。

来源：[constraints](https://www.postgresql.org/docs/17/ddl-constraints.html)；PostgreSQL17 §5.5.1 and §5.5.3; response-sha256:f5cb96e972b61ae884b4ac4e9a7834f8d3b74703d094ddf6e0ae28570487bb9c；PostgreSQL17 §5.5.1 and §5.5.3。规范摘要（AI中文改写，待人工核验，非逐字引句）：唯一约束保护指定列组合；默认NULL互异，NULLS NOT DISTINCT可改变。CHECK为true或NULL都满足，故必填须NOT NULL；跨行限制不能由引用其他行的CHECK持续保证，可按不变量选择UNIQUE、EXCLUDE或外键。

本判断短引定位：new or updated row being checked

变化依据：由“应用把订单号全表不重复写成调用查其他行函数的CHECK；后续别行更新及备份恢复均需保持规则。”变为“业务规则改为同资源预订时间不得重叠；订单号唯一无法表达，且边界相接允许。”，故“以真正跨行唯一约束表达订单号规则，迁移前先核对并处理已有重复。”改为“按时间区间与资源设计排斥约束或等价串行边界，并明确边界语义后验证。”。

仅改名反例：跨行规则与恢复一致性（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：PostgreSQL不支持用此类CHECK持续保证跨行规则，迁移仍需处理已有数据。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## data.query-1 — 执行计划里的数字是什么

状态：pending_human_review；技术背景：data-evidence-v1；档位：基础

**原题**

普通EXPLAIN显示cost=10000；没有ANALYZE实际耗时、扫描行数或等待证据。

可接受：把cost视为估计单位，先在安全环境补实际耗时和行数。

明确错误：把10000直接报告为线上耗时10000毫秒。

依据候选：估计cost不是实际毫秒，材料不足以确认耗时或瓶颈。

反例：反例：普通EXPLAIN显示cost=10000；没有ANALYZE实际耗时、扫描行数或等待证据。 因此“把10000直接报告为线上耗时10000毫秒。”不成立。

来源：[explain](https://www.postgresql.org/docs/17/using-explain.html)；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE; response-sha256:99f0ed28fc7d50c7bee8f51d5bd3107bd3e0e138f04c0aa9dd7ecf127d316e70；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE。规范摘要（AI中文改写，待人工核验，非逐字引句）：ANALYZE会实际执行语句并报告实际行数和耗时；普通EXPLAIN的cost是估计单位，不是毫秒。只能基于明确安全环境选择测量，不能把写语句分析当纯只读。

本判断短引定位：cost estimates are expressed in arbitrary units

**实质变式候选**

受控只读EXPLAIN ANALYZE显示actual time=120ms，实际扫描大部分表且无锁等待。

可接受：报告该测量下的实际时间并结合扫描选择性评估索引，不混为cost。

明确错误：把10000直接报告为线上耗时10000毫秒。

依据候选：已提供真实受控测量后可以使用实际时间，但不能宣称生产普遍如此。

反例：反例：受控只读EXPLAIN ANALYZE显示actual time=120ms，实际扫描大部分表且无锁等待。 因此“把10000直接报告为线上耗时10000毫秒。”不成立。

来源：[explain](https://www.postgresql.org/docs/17/using-explain.html)；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE; response-sha256:99f0ed28fc7d50c7bee8f51d5bd3107bd3e0e138f04c0aa9dd7ecf127d316e70；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE。规范摘要（AI中文改写，待人工核验，非逐字引句）：ANALYZE会实际执行语句并报告实际行数和耗时；普通EXPLAIN的cost是估计单位，不是毫秒。只能基于明确安全环境选择测量，不能把写语句分析当纯只读。

本判断短引定位：EXPLAIN actually executes the query

变化依据：由“普通EXPLAIN显示cost=10000；没有ANALYZE实际耗时、扫描行数或等待证据。”变为“受控只读EXPLAIN ANALYZE显示actual time=120ms，实际扫描大部分表且无锁等待。”，故“把cost视为估计单位，先在安全环境补实际耗时和行数。”改为“报告该测量下的实际时间并结合扫描选择性评估索引，不混为cost。”。

仅改名反例：执行计划里的数字是什么（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：估计cost不是实际毫秒，材料不足以确认耗时或瓶颈。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## data.query-2 — 慢请求等待的是谁

状态：pending_human_review；技术背景：data-evidence-v1；档位：进阶

**原题**

查询使用匹配索引，执行前一直等待另一事务的ACCESS EXCLUSIVE锁；阻塞事务尚未结束。

可接受：核查持锁事务和结束条件，不能先用新索引解释该等待。

明确错误：继续加同样索引即可立即消除锁等待。

依据候选：锁冲突与扫描成本不同；该锁会阻塞普通SELECT。

反例：反例：查询使用匹配索引，执行前一直等待另一事务的ACCESS EXCLUSIVE锁；阻塞事务尚未结束。 因此“继续加同样索引即可立即消除锁等待。”不成立。

来源：[locks](https://www.postgresql.org/docs/17/explicit-locking.html)；PostgreSQL17 §13.3 Table/row locks and deadlocks; response-sha256:bfac5eecf19fc00675d37adbb11572f76cf724739bba9b5a15e66a46546d580a；PostgreSQL17 §13.3 Table/row locks and deadlocks。规范摘要（AI中文改写，待人工核验，非逐字引句）：锁通常持有到事务结束；普通SELECT与行写锁的关系不同于ACCESS EXCLUSIVE。多对象按一致顺序取锁可避免对应循环等待；仍须处理其他死锁和事务重试。

本判断短引定位：Only an ACCESS EXCLUSIVE lock blocks a SELECT

来源：[explain](https://www.postgresql.org/docs/17/using-explain.html)；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE; response-sha256:99f0ed28fc7d50c7bee8f51d5bd3107bd3e0e138f04c0aa9dd7ecf127d316e70；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE。规范摘要（AI中文改写，待人工核验，非逐字引句）：ANALYZE会实际执行语句并报告实际行数和耗时；普通EXPLAIN的cost是估计单位，不是毫秒。只能基于明确安全环境选择测量，不能把写语句分析当纯只读。

本判断短引定位：EXPLAIN actually executes the query

**实质变式候选**

阻塞事务已提交；当前没有锁等待，计划显示过滤列无匹配索引且扫描99%无关行。

可接受：转向选择性和执行计划验证，比较索引代价与实际扫描。

明确错误：继续加同样索引即可立即消除锁等待。

依据候选：等待事实已消失，现有扫描证据支持另一条诊断路径。

反例：反例：阻塞事务已提交；当前没有锁等待，计划显示过滤列无匹配索引且扫描99%无关行。 因此“继续加同样索引即可立即消除锁等待。”不成立。

来源：[locks](https://www.postgresql.org/docs/17/explicit-locking.html)；PostgreSQL17 §13.3 Table/row locks and deadlocks; response-sha256:bfac5eecf19fc00675d37adbb11572f76cf724739bba9b5a15e66a46546d580a；PostgreSQL17 §13.3 Table/row locks and deadlocks。规范摘要（AI中文改写，待人工核验，非逐字引句）：锁通常持有到事务结束；普通SELECT与行写锁的关系不同于ACCESS EXCLUSIVE。多对象按一致顺序取锁可避免对应循环等待；仍须处理其他死锁和事务重试。

本判断短引定位：Only an ACCESS EXCLUSIVE lock blocks a SELECT

来源：[explain](https://www.postgresql.org/docs/17/using-explain.html)；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE; response-sha256:99f0ed28fc7d50c7bee8f51d5bd3107bd3e0e138f04c0aa9dd7ecf127d316e70；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE。规范摘要（AI中文改写，待人工核验，非逐字引句）：ANALYZE会实际执行语句并报告实际行数和耗时；普通EXPLAIN的cost是估计单位，不是毫秒。只能基于明确安全环境选择测量，不能把写语句分析当纯只读。

本判断短引定位：EXPLAIN actually executes the query

变化依据：由“查询使用匹配索引，执行前一直等待另一事务的ACCESS EXCLUSIVE锁；阻塞事务尚未结束。”变为“阻塞事务已提交；当前没有锁等待，计划显示过滤列无匹配索引且扫描99%无关行。”，故“核查持锁事务和结束条件，不能先用新索引解释该等待。”改为“转向选择性和执行计划验证，比较索引代价与实际扫描。”。

仅改名反例：慢请求等待的是谁（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：锁冲突与扫描成本不同；该锁会阻塞普通SELECT。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## data.query-3 — 两表相反顺序与写分析风险

状态：pending_human_review；技术背景：data-evidence-v1；档位：综合

**原题**

事务A锁账户再锁订单；B锁订单再锁账户，已形成循环等待；有人建议生产EXPLAIN ANALYZE更新语句排查。

可接受：统一对象取锁顺序并处理事务重试；写分析改在可控隔离环境验证。

明确错误：添加索引后反向锁顺序必定安全，写ANALYZE也不会真的写。

依据候选：一致锁顺序能避免此循环；ANALYZE会实际执行，不能把排查变成未授权写入。

反例：反例：事务A锁账户再锁订单；B锁订单再锁账户，已形成循环等待；有人建议生产EXPLAIN ANALYZE更新语句排查。 因此“添加索引后反向锁顺序必定安全，写ANALYZE也不会真的写。”不成立。

来源：[locks](https://www.postgresql.org/docs/17/explicit-locking.html)；PostgreSQL17 §13.3 Table/row locks and deadlocks; response-sha256:bfac5eecf19fc00675d37adbb11572f76cf724739bba9b5a15e66a46546d580a；PostgreSQL17 §13.3 Table/row locks and deadlocks。规范摘要（AI中文改写，待人工核验，非逐字引句）：锁通常持有到事务结束；普通SELECT与行写锁的关系不同于ACCESS EXCLUSIVE。多对象按一致顺序取锁可避免对应循环等待；仍须处理其他死锁和事务重试。

本判断短引定位：locks on multiple objects in a consistent order

来源：[explain](https://www.postgresql.org/docs/17/using-explain.html)；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE; response-sha256:99f0ed28fc7d50c7bee8f51d5bd3107bd3e0e138f04c0aa9dd7ecf127d316e70；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE。规范摘要（AI中文改写，待人工核验，非逐字引句）：ANALYZE会实际执行语句并报告实际行数和耗时；普通EXPLAIN的cost是估计单位，不是毫秒。只能基于明确安全环境选择测量，不能把写语句分析当纯只读。

本判断短引定位：EXPLAIN actually executes the query

**实质变式候选**

两事务已按同顺序取锁，无死锁；实际慢因长事务持锁等待远程调用，写分析尚未执行。

可接受：缩短合法事务持锁区间并核对外部调用边界，在隔离环境验证，不能宣称顺序修复解决所有等待。

明确错误：添加索引后反向锁顺序必定安全，写ANALYZE也不会真的写。

依据候选：相同顺序不能消除长事务等待，改变后的证据要求核对持锁时间。

反例：反例：两事务已按同顺序取锁，无死锁；实际慢因长事务持锁等待远程调用，写分析尚未执行。 因此“添加索引后反向锁顺序必定安全，写ANALYZE也不会真的写。”不成立。

来源：[locks](https://www.postgresql.org/docs/17/explicit-locking.html)；PostgreSQL17 §13.3 Table/row locks and deadlocks; response-sha256:bfac5eecf19fc00675d37adbb11572f76cf724739bba9b5a15e66a46546d580a；PostgreSQL17 §13.3 Table/row locks and deadlocks。规范摘要（AI中文改写，待人工核验，非逐字引句）：锁通常持有到事务结束；普通SELECT与行写锁的关系不同于ACCESS EXCLUSIVE。多对象按一致顺序取锁可避免对应循环等待；仍须处理其他死锁和事务重试。

本判断短引定位：locks on multiple objects in a consistent order

来源：[explain](https://www.postgresql.org/docs/17/using-explain.html)；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE; response-sha256:99f0ed28fc7d50c7bee8f51d5bd3107bd3e0e138f04c0aa9dd7ecf127d316e70；PostgreSQL17 §14.1.2 EXPLAIN ANALYZE。规范摘要（AI中文改写，待人工核验，非逐字引句）：ANALYZE会实际执行语句并报告实际行数和耗时；普通EXPLAIN的cost是估计单位，不是毫秒。只能基于明确安全环境选择测量，不能把写语句分析当纯只读。

本判断短引定位：EXPLAIN actually executes the query

变化依据：由“事务A锁账户再锁订单；B锁订单再锁账户，已形成循环等待；有人建议生产EXPLAIN ANALYZE更新语句排查。”变为“两事务已按同顺序取锁，无死锁；实际慢因长事务持锁等待远程调用，写分析尚未执行。”，故“统一对象取锁顺序并处理事务重试；写分析改在可控隔离环境验证。”改为“缩短合法事务持锁区间并核对外部调用边界，在隔离环境验证，不能宣称顺序修复解决所有等待。”。

仅改名反例：两表相反顺序与写分析风险（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：一致锁顺序能避免此循环；ANALYZE会实际执行，不能把排查变成未授权写入。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## async.cache-1 — no-cache并非不能保存

状态：pending_human_review；技术背景：async-evidence-v1；档位：基础

**原题**

响应带无参数no-cache；缓存已有副本但本次尚未向源站验证。

可接受：允许保留副本，但本次复用前必须取得成功验证。

明确错误：no-cache表示副本不可存在，或存在就能直接使用。

依据候选：no-cache约束复用验证，不能混同no-store或无条件复用。

反例：反例：响应带无参数no-cache；缓存已有副本但本次尚未向源站验证。 因此“no-cache表示副本不可存在，或存在就能直接使用。”不成立。

来源：[cache](https://www.rfc-editor.org/rfc/rfc9111.txt)；RFC9111 (2022); response-sha256:aeb52adb3279d5f23dae34f68af11bd5cef0a0aff7ffcd014c9ca93c5302cf3e；RFC9111 (2022), §3.5/§5.2.2.2/§5.2.2.4/§5.2.2.5。规范摘要（AI中文改写，待人工核验，非逐字引句）：无参数no-cache不禁止存储，但复用必须先成功验证；no-store禁止存储。must-revalidate过期且无法联系源站时不得复用旧响应。带Authorization请求的共享缓存仅在响应显式允许等条件满足时可用，不能把max-age单独当授权，也不能据此忽略业务对象权限。

本判断短引定位：forwarding it for validation and receiving a successful response

**实质变式候选**

响应改为no-store，尚未写入缓存。

可接受：不存储该响应，也不把它作为后续缓存命中。

明确错误：no-cache表示副本不可存在，或存在就能直接使用。

依据候选：改变后的指令禁止存储，不能继续沿用仅重验证策略。

反例：反例：响应改为no-store，尚未写入缓存。 因此“no-cache表示副本不可存在，或存在就能直接使用。”不成立。

来源：[cache](https://www.rfc-editor.org/rfc/rfc9111.txt)；RFC9111 (2022); response-sha256:aeb52adb3279d5f23dae34f68af11bd5cef0a0aff7ffcd014c9ca93c5302cf3e；RFC9111 (2022), §3.5/§5.2.2.2/§5.2.2.4/§5.2.2.5。规范摘要（AI中文改写，待人工核验，非逐字引句）：无参数no-cache不禁止存储，但复用必须先成功验证；no-store禁止存储。must-revalidate过期且无法联系源站时不得复用旧响应。带Authorization请求的共享缓存仅在响应显式允许等条件满足时可用，不能把max-age单独当授权，也不能据此忽略业务对象权限。

本判断短引定位：MUST NOT store any part

变化依据：由“响应带无参数no-cache；缓存已有副本但本次尚未向源站验证。”变为“响应改为no-store，尚未写入缓存。”，故“允许保留副本，但本次复用前必须取得成功验证。”改为“不存储该响应，也不把它作为后续缓存命中。”。

仅改名反例：no-cache并非不能保存（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：no-cache约束复用验证，不能混同no-store或无条件复用。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## async.cache-2 — 离线时的过期价格

状态：pending_human_review；技术背景：async-evidence-v1；档位：进阶

**原题**

响应已过期且有must-revalidate；源站不可达，没有任何新验证成功证据。

可接受：返回明确不可取得有效响应的错误，不复用该过期值冒新价格。

明确错误：断网自动忽略must-revalidate，用旧价继续确认交易。

依据候选：must-revalidate在断网时也必须遵守，源站不可达不能成为绕过条件。

反例：反例：响应已过期且有must-revalidate；源站不可达，没有任何新验证成功证据。 因此“断网自动忽略must-revalidate，用旧价继续确认交易。”不成立。

来源：[cache](https://www.rfc-editor.org/rfc/rfc9111.txt)；RFC9111 (2022); response-sha256:aeb52adb3279d5f23dae34f68af11bd5cef0a0aff7ffcd014c9ca93c5302cf3e；RFC9111 (2022), §3.5/§5.2.2.2/§5.2.2.4/§5.2.2.5。规范摘要（AI中文改写，待人工核验，非逐字引句）：无参数no-cache不禁止存储，但复用必须先成功验证；no-store禁止存储。must-revalidate过期且无法联系源站时不得复用旧响应。带Authorization请求的共享缓存仅在响应显式允许等条件满足时可用，不能把max-age单独当授权，也不能据此忽略业务对象权限。

本判断短引定位：MUST generate an error response

**实质变式候选**

源站恢复并成功验证当前副本仍有效；权限与缓存键均匹配。

可接受：按成功验证后的有效副本响应，并保留此次验证事实。

明确错误：断网自动忽略must-revalidate，用旧价继续确认交易。

依据候选：新证据补齐验证条件，不能继续把已成功验证状态当作离线未知。

反例：反例：源站恢复并成功验证当前副本仍有效；权限与缓存键均匹配。 因此“断网自动忽略must-revalidate，用旧价继续确认交易。”不成立。

来源：[cache](https://www.rfc-editor.org/rfc/rfc9111.txt)；RFC9111 (2022); response-sha256:aeb52adb3279d5f23dae34f68af11bd5cef0a0aff7ffcd014c9ca93c5302cf3e；RFC9111 (2022), §3.5/§5.2.2.2/§5.2.2.4/§5.2.2.5。规范摘要（AI中文改写，待人工核验，非逐字引句）：无参数no-cache不禁止存储，但复用必须先成功验证；no-store禁止存储。must-revalidate过期且无法联系源站时不得复用旧响应。带Authorization请求的共享缓存仅在响应显式允许等条件满足时可用，不能把max-age单独当授权，也不能据此忽略业务对象权限。

本判断短引定位：MUST generate an error response

变化依据：由“响应已过期且有must-revalidate；源站不可达，没有任何新验证成功证据。”变为“源站恢复并成功验证当前副本仍有效；权限与缓存键均匹配。”，故“返回明确不可取得有效响应的错误，不复用该过期值冒新价格。”改为“按成功验证后的有效副本响应，并保留此次验证事实。”。

仅改名反例：离线时的过期价格（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：must-revalidate在断网时也必须遵守，源站不可达不能成为绕过条件。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## async.cache-3 — 带身份请求能否共享缓存

状态：pending_human_review；技术背景：async-evidence-v1；档位：综合

**原题**

带Authorization的请求得到仅max-age=60的响应；共享缓存拟把它供其他请求复用，无public/s-maxage/must-revalidate等显式许可。

可接受：不据max-age单独允许共享复用，保留身份与业务权限边界。

明确错误：新鲜度足够就能忽略Authorization把响应给任意账号。

依据候选：共享缓存还需显式允许等条件；新鲜度不能代替授权。

反例：反例：带Authorization的请求得到仅max-age=60的响应；共享缓存拟把它供其他请求复用，无public/s-maxage/must-revalidate等显式许可。 因此“新鲜度足够就能忽略Authorization把响应给任意账号。”不成立。

来源：[cache](https://www.rfc-editor.org/rfc/rfc9111.txt)；RFC9111 (2022); response-sha256:aeb52adb3279d5f23dae34f68af11bd5cef0a0aff7ffcd014c9ca93c5302cf3e；RFC9111 (2022), §3.5/§5.2.2.2/§5.2.2.4/§5.2.2.5。规范摘要（AI中文改写，待人工核验，非逐字引句）：无参数no-cache不禁止存储，但复用必须先成功验证；no-store禁止存储。must-revalidate过期且无法联系源站时不得复用旧响应。带Authorization请求的共享缓存仅在响应显式允许等条件满足时可用，不能把max-age单独当授权，也不能据此忽略业务对象权限。

本判断短引定位：explicitly allows shared caching

**实质变式候选**

源站明确public且内容是各账号相同的公开汇总；缓存键Vary匹配、仍新鲜，业务确认允许公开。

可接受：在这些冻结条件下可共享该公开汇总，不能外推私人详情。

明确错误：新鲜度足够就能忽略Authorization把响应给任意账号。

依据候选：明确缓存许可与公开内容证据改变可复用结论，权限范围仍限此汇总。

反例：反例：源站明确public且内容是各账号相同的公开汇总；缓存键Vary匹配、仍新鲜，业务确认允许公开。 因此“新鲜度足够就能忽略Authorization把响应给任意账号。”不成立。

来源：[cache](https://www.rfc-editor.org/rfc/rfc9111.txt)；RFC9111 (2022); response-sha256:aeb52adb3279d5f23dae34f68af11bd5cef0a0aff7ffcd014c9ca93c5302cf3e；RFC9111 (2022), §3.5/§5.2.2.2/§5.2.2.4/§5.2.2.5。规范摘要（AI中文改写，待人工核验，非逐字引句）：无参数no-cache不禁止存储，但复用必须先成功验证；no-store禁止存储。must-revalidate过期且无法联系源站时不得复用旧响应。带Authorization请求的共享缓存仅在响应显式允许等条件满足时可用，不能把max-age单独当授权，也不能据此忽略业务对象权限。

本判断短引定位：explicitly allows shared caching

变化依据：由“带Authorization的请求得到仅max-age=60的响应；共享缓存拟把它供其他请求复用，无public/s-maxage/must-revalidate等显式许可。”变为“源站明确public且内容是各账号相同的公开汇总；缓存键Vary匹配、仍新鲜，业务确认允许公开。”，故“不据max-age单独允许共享复用，保留身份与业务权限边界。”改为“在这些冻结条件下可共享该公开汇总，不能外推私人详情。”。

仅改名反例：带身份请求能否共享缓存（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：共享缓存还需显式允许等条件；新鲜度不能代替授权。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## async.jobs-1 — 发布确认不是处理完成

状态：pending_human_review；技术背景：async-evidence-v1；档位：基础

**原题**

发布者收到publisher confirm；消费者尚未领取消息，没有业务提交记录。

可接受：只记录消息获发布确认，等待消费者处理与业务结果。

明确错误：收到发布确认就把订单标记已完成。

依据候选：发布确认和消费确认独立，前者不证明业务处理结束。

反例：反例：发布者收到publisher confirm；消费者尚未领取消息，没有业务提交记录。 因此“收到发布确认就把订单标记已完成。”不成立。

来源：[jobs](https://www.rabbitmq.com/docs/4.1/confirms)；RabbitMQ4.1; response-sha256:6ff1469118e28b12c310e9a966c31c24c28fff2c16cb9538ef1d405584b8c0b3；RabbitMQ4.1, Consumer Acknowledgements and Publisher Confirms。规范摘要（AI中文改写，待人工核验，非逐字引句）：发布确认只覆盖发布者到节点/队列，不证明消费者已处理。手动确认下连接关闭会重排未确认投递；消费者必须处理重投和幂等。已确认后丢失本地处理成果不能期待队列自动恢复；外部副作用另有事务边界。

本判断短引定位：entirely orthogonal and unaware of each other

**实质变式候选**

消费者已提交业务结果并发送手动确认，业务记录可核对。

可接受：依据已提交业务记录展示完成，确认只作投递生命周期证据。

明确错误：收到发布确认就把订单标记已完成。

依据候选：新增业务提交事实才支撑完成，不能把之前的发布确认追认成处理成功。

反例：反例：消费者已提交业务结果并发送手动确认，业务记录可核对。 因此“收到发布确认就把订单标记已完成。”不成立。

来源：[jobs](https://www.rabbitmq.com/docs/4.1/confirms)；RabbitMQ4.1; response-sha256:6ff1469118e28b12c310e9a966c31c24c28fff2c16cb9538ef1d405584b8c0b3；RabbitMQ4.1, Consumer Acknowledgements and Publisher Confirms。规范摘要（AI中文改写，待人工核验，非逐字引句）：发布确认只覆盖发布者到节点/队列，不证明消费者已处理。手动确认下连接关闭会重排未确认投递；消费者必须处理重投和幂等。已确认后丢失本地处理成果不能期待队列自动恢复；外部副作用另有事务边界。

本判断短引定位：entirely orthogonal and unaware of each other

变化依据：由“发布者收到publisher confirm；消费者尚未领取消息，没有业务提交记录。”变为“消费者已提交业务结果并发送手动确认，业务记录可核对。”，故“只记录消息获发布确认，等待消费者处理与业务结果。”改为“依据已提交业务记录展示完成，确认只作投递生命周期证据。”。

仅改名反例：发布确认不是处理完成（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：发布确认和消费确认独立，前者不证明业务处理结束。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## async.jobs-2 — 提交后未确认的重投

状态：pending_human_review；技术背景：async-evidence-v1；档位：进阶

**原题**

消费者完成数据库写入后连接断开，尚未发送手动ack；同业务任务再次投递。

可接受：按持久业务身份核对并抑制重复效果，再按当前投递确认。

明确错误：未ack说明业务没写入，重新累加一次。

依据候选：未确认投递可重排；业务提交与消息确认不是同一事实。

反例：反例：消费者完成数据库写入后连接断开，尚未发送手动ack；同业务任务再次投递。 因此“未ack说明业务没写入，重新累加一次。”不成立。

来源：[jobs](https://www.rabbitmq.com/docs/4.1/confirms)；RabbitMQ4.1; response-sha256:6ff1469118e28b12c310e9a966c31c24c28fff2c16cb9538ef1d405584b8c0b3；RabbitMQ4.1, Consumer Acknowledgements and Publisher Confirms。规范摘要（AI中文改写，待人工核验，非逐字引句）：发布确认只覆盖发布者到节点/队列，不证明消费者已处理。手动确认下连接关闭会重排未确认投递；消费者必须处理重投和幂等。已确认后丢失本地处理成果不能期待队列自动恢复；外部副作用另有事务边界。

本判断短引定位：automatically requeued

**实质变式候选**

旧消费者在写入前断开且库内确定没有该业务身份；新投递已获唯一受理。

可接受：执行一次业务写入并持久记录，完成后确认。

明确错误：未ack说明业务没写入，重新累加一次。

依据候选：确认缺失相同但实际业务提交证据不同，因此不能一律跳过重投。

反例：反例：旧消费者在写入前断开且库内确定没有该业务身份；新投递已获唯一受理。 因此“未ack说明业务没写入，重新累加一次。”不成立。

来源：[jobs](https://www.rabbitmq.com/docs/4.1/confirms)；RabbitMQ4.1; response-sha256:6ff1469118e28b12c310e9a966c31c24c28fff2c16cb9538ef1d405584b8c0b3；RabbitMQ4.1, Consumer Acknowledgements and Publisher Confirms。规范摘要（AI中文改写，待人工核验，非逐字引句）：发布确认只覆盖发布者到节点/队列，不证明消费者已处理。手动确认下连接关闭会重排未确认投递；消费者必须处理重投和幂等。已确认后丢失本地处理成果不能期待队列自动恢复；外部副作用另有事务边界。

本判断短引定位：automatically requeued

变化依据：由“消费者完成数据库写入后连接断开，尚未发送手动ack；同业务任务再次投递。”变为“旧消费者在写入前断开且库内确定没有该业务身份；新投递已获唯一受理。”，故“按持久业务身份核对并抑制重复效果，再按当前投递确认。”改为“执行一次业务写入并持久记录，完成后确认。”。

仅改名反例：提交后未确认的重投（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：未确认投递可重排；业务提交与消息确认不是同一事实。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。

## async.jobs-3 — 外部效果未知与确认丢失

状态：pending_human_review；技术背景：async-evidence-v1；档位：综合

**原题**

消费者调用外部计费后响应丢失，库内仍pending，消息未ack且会重投；外部没有参与本地事务。

可接受：保持未知状态，用持久业务身份核对外部结果并防重复，再决定补偿或确认。

明确错误：回滚本地事务已自动撤销外部计费，可以直接再次扣费。

依据候选：队列重投需幂等，外部效果不能由本地事务推断，未知时必须补证。

反例：反例：消费者调用外部计费后响应丢失，库内仍pending，消息未ack且会重投；外部没有参与本地事务。 因此“回滚本地事务已自动撤销外部计费，可以直接再次扣费。”不成立。

来源：[jobs](https://www.rabbitmq.com/docs/4.1/confirms)；RabbitMQ4.1; response-sha256:6ff1469118e28b12c310e9a966c31c24c28fff2c16cb9538ef1d405584b8c0b3；RabbitMQ4.1, Consumer Acknowledgements and Publisher Confirms。规范摘要（AI中文改写，待人工核验，非逐字引句）：发布确认只覆盖发布者到节点/队列，不证明消费者已处理。手动确认下连接关闭会重排未确认投递；消费者必须处理重投和幂等。已确认后丢失本地处理成果不能期待队列自动恢复；外部副作用另有事务边界。

本判断短引定位：implemented with idempotence in mind

**实质变式候选**

外部查询明确已扣费，本地仍pending且同业务任务重投。

可接受：把已核对外部结果恢复进本地同业务记录，避免再次扣费，再确认消息。

明确错误：回滚本地事务已自动撤销外部计费，可以直接再次扣费。

依据候选：外部结果已从未知变确定，恢复应补本地记录而非再次执行外部效果。

反例：反例：外部查询明确已扣费，本地仍pending且同业务任务重投。 因此“回滚本地事务已自动撤销外部计费，可以直接再次扣费。”不成立。

来源：[jobs](https://www.rabbitmq.com/docs/4.1/confirms)；RabbitMQ4.1; response-sha256:6ff1469118e28b12c310e9a966c31c24c28fff2c16cb9538ef1d405584b8c0b3；RabbitMQ4.1, Consumer Acknowledgements and Publisher Confirms。规范摘要（AI中文改写，待人工核验，非逐字引句）：发布确认只覆盖发布者到节点/队列，不证明消费者已处理。手动确认下连接关闭会重排未确认投递；消费者必须处理重投和幂等。已确认后丢失本地处理成果不能期待队列自动恢复；外部副作用另有事务边界。

本判断短引定位：implemented with idempotence in mind

变化依据：由“消费者调用外部计费后响应丢失，库内仍pending，消息未ack且会重投；外部没有参与本地事务。”变为“外部查询明确已扣费，本地仍pending且同业务任务重投。”，故“保持未知状态，用持久业务身份核对外部结果并防重复，再决定补偿或确认。”改为“把已核对外部结果恢复进本地同业务记录，避免再次扣费，再确认消息。”。

仅改名反例：外部效果未知与确认丢失（换名版本）（其余事实/规则不变，不能作为陌生检验）

方向帮助候选：队列重投需幂等，外部效果不能由本地事务推断，未知时必须补证。

人工检查：来源适用性、假设充分性、标签、多解/补证、变式、帮助方向。结论待填，不预签。
