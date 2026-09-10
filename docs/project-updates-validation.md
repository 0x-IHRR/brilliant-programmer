# 项目更新与来源失效

更新由用户主动发起，不监控上游。ProjectRun 固定仓库 commit、focus 与行范围；同版本复用同时比较完整范围。新项目路线以不可变前版本关联到原路线，当前已确认版本是单独的服务端指针。User 事务锁串行确认，旧 CAS 不能覆盖新选择；新候选未确认时仍明确展示、使用原已确认版本。已有 ProjectInput/Version/Materials 的不可变保护保持不变。

节点完成只来自原轮正式完成事实。跨新读取身份仍须相同 commit、完整读取范围、目标、重点、能力键和引用才保留节点 ID；排序保 ID，目标变化产生新 ID。旧完成记录始终可追溯，不因此重复发奖或授证。本机未保存编辑按 Topic 和节点双身份隔离，与跨版本完成身份分开。

## 已有验证

- 核心 API/CAS/读取范围 5 项通过；独立 worker 和受控 TLS 验证同 Topic 修改重点后，未确认候选不改变旧已确认目标实际出题，1 项通过。
- 受控 GitHub 404/403 走实际 worker，新读取失败且不外呼模型，原 snapshot/map/attempt 完整保留，2 项通过。
- 两候选并发确认只有一个成功、停止后旧任务不可 retry 且显式新请求身份可创建，2 项通过。
- 真实浏览器先复现 A 未保存草稿串到共享节点 ID 的 B；修复后 A/B 编辑分别保存、B 保存不删除 A 草稿、重读保本机稿通过。路线 B 由实际队列和两次受控模型分析/核对创建。
- 真实独立 schema 从 0026 升级 0027，12 张表共 12 行原始记录保持不变，真实 active 指针回填、重复 upgrade 幂等、更新关联 UPDATE/DELETE 均被拒绝。保留 schema `issue24_migration_cdb66bc7`，没有 stamp。

这些分次检查不是一个完整测试总数。完整回归与最终浏览器结果在最终冻结后补记。受控模型证明软件协议，不代表实际教学语义已经认证；未调用付费模型、执行目标项目或部署。

## 实现容量边界

路线读取在短只读快照中汇集此项目路线历代记录。没有新的学习数量上限、缓存或后台投影；当前列表会重复读取各路线关联的历史，成本随路线版本和已保留题目数增加，大规模性能尚未验证。完整源码或目标变更不自动做语义对齐。用户永久删除本地项目范围由后续功能处理，上游不可读不代替该授权。

最新专项组合 19 passed（18.37s）；随后仅将停止用例终态断言改成按 captured request ID 查询，而非列表位置，保原消费者 15 秒、总 3 次调用与已知用量断言。完整原答流程再验证了跨新读取身份完成衔接、重排保完成、修改重点不冒旧完成与原轮唯一 10 点。

新增浏览器完整脚本最终 1 passed（1.6s）：先前多路线 select 在 320px 实测宽 361px 导致横溢，局部宽度限制后原断言通过；键盘确认、独立 API 重读当前指针、320px/200% 均通过。截图 `/tmp/bp-issue-24-artifacts/project-updates-320.png` 和 `project-updates-200.png`。原生选择框宽度修复不更改服务端行为。前端 7 unit、ruff、backend strict mypy 116、build、diff check 通过。

真正 commit A→B 的新增专项已编写：受控 GitHub 两次实际读取，B 的 commit/tree/blob/源码片段变化；两阶段独立 worker/TLS 生成路线并显式确认，逐字段比较旧 TrainingRun、Evaluation（包含原 inputs/sources/result）、Submission 和唯一奖励。首跑因测试切换模型配置漏 expected_version，被真实配置 CAS 拒绝；改为 GET 当前版本后显式 PUT 并断言 200，再独占执行 1 passed（15.85s）。旧 TrainingRun、Evaluation、原答和奖励完整比较通过。最新 CI 将再执行该用例。

本地完整后端固定 1acd61e 自然完成：829 passed、1 条既有 Starlette warning、1099.28s，临时目录 `/tmp/bp-issue-24-pytest-full-10`。新增 A→B 后来单独通过，不能写作同次 830 全绿；最终同 HEAD 全量以 CI 为准。
