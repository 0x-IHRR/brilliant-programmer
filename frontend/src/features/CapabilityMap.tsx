import { LearningUnit } from "./LearningUnit"
import { useEffect, useState } from "react"
import { CapabilitiesService, type Catalog, type EvidenceKey, type EvidenceMap } from "../client"
import { Button } from "../components/ui/button"
import { Label } from "../components/ui/label"

export function CapabilityMap() {
  const [selectedUnit, setSelectedUnit] = useState<EvidenceKey | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [evidence, setEvidence] = useState<EvidenceMap | null>(null)
  const [evidenceError, setEvidenceError] = useState("")
  const [error, setError] = useState("")
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [domainId, setDomainId] = useState("")
  const [difficulty, setDifficulty] = useState<"基础" | "进阶" | "综合">("基础")
  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    setEvidenceError("")
    void CapabilitiesService.readCapabilityEvidence().then(({ data }) => {
      if (active) setEvidence(data)
    }).catch(() => { if (active) setEvidenceError("能力证据读取失败，已有结果保留；请重试确认最新状态。") })
    void CapabilitiesService.readCatalog().then(({ data }) => {
      if (active) { setCatalog(data); const query = new URLSearchParams(location.search); const cap = data.domains.flatMap(d => d.capabilities).find(c => c.id === query.get("capability")); const tier = query.get("difficulty"); if (cap && (tier === "基础" || tier === "进阶" || tier === "综合")) { setSelectedUnit({ capability_id: cap.id, difficulty: tier, background_id: cap.background_id }); setDifficulty(tier) } }
    }).catch(() => {
      if (active) setError("目录读取失败，请检查登录状态或重试。已有目录保留，未获得新的验证结果。")
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [attempt])

  const capabilities = catalog?.domains.flatMap(d => d.capabilities) ?? []
  function describe(key: EvidenceKey) {
    const capability = capabilities.find(c => c.id === key.capability_id)
    const background = catalog?.backgrounds.find(b => b.id === key.background_id)
    return `${capability?.title ?? key.capability_id} · ${key.difficulty} · ${background?.name ?? key.background_id}`
  }
  const control = "block w-full min-w-0 rounded border p-2 focus-visible:outline-2 focus-visible:outline-offset-2"
  return <section aria-labelledby="capability-map-title" className="space-y-4 break-words">
    <h2 id="capability-map-title" className="text-xl font-semibold">全栈能力与前置地图</h2>
    <p>未验证表示还没有对应证据，不表示不会。查看领域或难度不会解锁关卡，也不会改变等级。</p>
    <p>按同一能力、难度、技术背景的两个实质不同陌生案例连续有效独立通过取证。普通练习不改变计数，未决争议不当失败；证明不因时间自动过期。已验证是本系统试行规则状态，真实模型评分与教学可靠性尚未验收。</p>
    {loading && <p aria-live="polite">正在读取能力目录…</p>}
    {evidenceError && <p role="alert">{evidenceError}</p>}
    {error && <p role="alert">{error}</p>}
    <Button className="h-auto min-h-9 max-w-full whitespace-normal" variant="outline" disabled={loading} onClick={() => setAttempt(n => n + 1)}>重新读取能力目录</Button>
    {catalog && <>
      <p>目录版本：{catalog.version} · {catalog.domains.length} 个领域</p>
      <p>{catalog.quality}</p>
      {selectedUnit && <LearningUnit key={JSON.stringify(selectedUnit)} initial={selectedUnit} catalog={catalog} />}
      <div>
        <Label htmlFor="capability-domain">查看领域</Label>
        <select id="capability-domain" className={control} value={domainId} onChange={e => setDomainId(e.target.value)}>
          <option value="">全部领域</option>
          {catalog.domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <fieldset>
        <legend>查看难度（仅筛选地图）</legend>
        <div className="flex flex-wrap gap-4">
          {(["基础", "进阶", "综合"] as const).map(d => <label key={d} className="flex items-center gap-2">
            <input type="radio" name="capability-difficulty" value={d} checked={difficulty === d} onChange={() => setDifficulty(d)} className="focus-visible:outline-2 focus-visible:outline-offset-2" />{d}
          </label>)}
        </div>
      </fieldset>
      <p>{difficulty}：{catalog.difficulty_criteria[difficulty]}</p>
      {catalog.domains.filter(d => !domainId || d.id === domainId).map(domain => <article key={domain.id} className="rounded border p-3 space-y-3">
        <h3 className="font-semibold">{domain.name}</h3>
        {domain.capabilities.map(capability => {
          const level = capability.levels.find(l => l.difficulty === difficulty)!
          const background = catalog.backgrounds.find(b => b.id === capability.background_id)!
          const proof = evidence?.states.find(item => item.target.capability_id === capability.id && item.target.difficulty === difficulty && item.target.background_id === capability.background_id)
          const stateName = !evidence ? "证据尚未读取" : proof?.status === "verified" ? "已验证" : proof?.status === "needs_consolidation" ? "待巩固" : "未验证"
          return <details key={capability.id} className="space-y-2">
            <summary className="cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2">{capability.title} · {difficulty} · {stateName}</summary>
            <p>当前连续独立通过：{evidence ? proof?.streak ?? 0 : "待读取"}；最近验证原答时间：{!evidence ? "待读取" : proof?.latest_verified_at ? new Date(proof.latest_verified_at).toLocaleString("zh-CN") : "尚无"}</p>
            {proof?.recovery_started_at_order != null && <p>从原答序号 {proof.recovery_started_at_order} 进入待巩固，只计算此后的两次连续新通过。</p>}
            {proof && <details><summary>查看状态依据（{(proof.history ?? []).length} 条原答）</summary>
              {(proof.history ?? []).map(item => <article key={item.evidence.original_id} className="border p-2 space-y-1 break-all">
                <p>原答序号 {item.evidence.order} · <time dateTime={item.evidence.submitted_at} title={item.evidence.submitted_at}>{new Date(item.evidence.submitted_at).toLocaleString("zh-CN")}</time></p>
                <p>{item.evidence.order_source === "legacy_created_at_uuid" ? "旧记录按原时间与ID稳定排序，无法补造过去精确先后。" : "原答受理时由服务端固定顺序。"}</p>
                <p>结果：{({ independent_pass_candidate: "有效独立通过候选", evidenced_fail: "有据失败", practice: "普通练习", unclear: "结论含糊", pending_delivery: "帮助交付待核实", system_failure: "系统失败", invalid_case: "无效案例", no_qualified_case: "无合格陌生案例", awaiting_evaluation: "等待有效评分", evidence_unavailable: "证据不可用", disputed: "未决争议" } as Record<string, string>)[item.evidence.outcome] ?? "待核实"}；{item.counted ? "计入此能力、难度与背景" : "未增加或打断连续次数"}；此时连续 {item.streak}，状态：{item.status === "verified" ? "已验证" : item.status === "needs_consolidation" ? "待巩固" : "未验证"}</p>
                <p>明确单独评分项：{item.evidence.judgment_ids.join("、") || "尚无"}；冻结事件：{item.evidence.frozen_sequence ?? "尚无"}</p>
                <a className="underline" href={`/?training_run=${item.evidence.run_id}`}>查看原轮与记录</a>
              </article>)}
            </details>}
            <Button className="h-auto min-h-9 max-w-full whitespace-normal" onClick={() => setSelectedUnit({ capability_id: capability.id, difficulty, background_id: capability.background_id })}>查看此目标的解锁与补基础路径</Button>
            <p className="break-all">稳定 ID：{capability.id}</p>
            <p>可观察判断：{capability.criterion}</p>
            <p>技术背景：{background.name}</p>
            <p>适用边界：{background.boundary}</p>
            {level.required?.length || level.alternatives?.length ? <>
              <p>前置证据条件（仅展示目录条件，不自动解锁）：</p>
              {!!level.required?.length && <div><p>以下全部必需：</p><ul className="list-disc pl-5">
                {level.required.map(key => <li key={JSON.stringify(key)}>{describe(key)}</li>)}
              </ul></div>}
              {level.alternatives?.map((group, index) => <div key={index}><p>替代组 {index + 1}：本组任选一项；每个替代组都需满足。</p><ul className="list-disc pl-5">
                {group.map(key => <li key={JSON.stringify(key)}>{describe(key)}</li>)}
              </ul></div>)}
            </> : <p>入门：无需先验能力证明。实际练习仍须满足账号、模型及案例质量条件。</p>}
          </details>
        })}
        <details className="space-y-2">
          <summary className="cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2">{difficulty}对照样例（说明定档，尚未人工核验）</summary>
          {domain.examples.filter(e => e.difficulty === difficulty).map(example => <div key={example.task} className="space-y-2">
            <p>情境：{example.task}</p>
            <p>有据判断：{example.acceptable}</p>
            <p>不足反例：{example.insufficient}</p>
          </div>)}
        </details>
      </article>)}
    </>}
  </section>
}
