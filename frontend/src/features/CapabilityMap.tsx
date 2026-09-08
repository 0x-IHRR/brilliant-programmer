import { useEffect, useState } from "react"
import { CapabilitiesService, type Catalog, type EvidenceKey } from "../client"
import { Button } from "../components/ui/button"
import { Label } from "../components/ui/label"

export function CapabilityMap() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState("")
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [domainId, setDomainId] = useState("")
  const [difficulty, setDifficulty] = useState<"基础" | "进阶" | "综合">("基础")
  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    void CapabilitiesService.readCatalog().then(({ data }) => {
      if (active) setCatalog(data)
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
    <p>独立检验与能力证明尚未接入。以后仅按同一能力、难度、技术背景的独立检验取证；不同框架或综合案例中仅出现过的组件不会自动获得证明。</p>
    {loading && <p aria-live="polite">正在读取能力目录…</p>}
    {error && <p role="alert">{error}</p>}
    <Button className="h-auto min-h-9 max-w-full whitespace-normal" variant="outline" disabled={loading} onClick={() => setAttempt(n => n + 1)}>重新读取能力目录</Button>
    {catalog && <>
      <p>目录版本：{catalog.version} · {catalog.domains.length} 个领域</p>
      <p>{catalog.quality}</p>
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
          return <details key={capability.id} className="space-y-2">
            <summary className="cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2">{capability.title} · {difficulty} · 未验证</summary>
            <p className="break-all">稳定 ID：{capability.id}</p>
            <p>可观察判断：{capability.criterion}</p>
            <p>技术背景：{background.name}</p>
            <p>适用边界：{background.boundary}</p>
            {level.required?.length || level.alternatives?.length ? <>
              <p>前置证据条件（当前尚未验证；不是对能力的否定）：</p>
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
