import { useEffect, useRef, useState } from "react"
import { CapabilitiesService, ModelconfigService, type Catalog, type EvidenceKey, type ModelConfigPublic, type UnitAccess } from "../client"
import { Button } from "../components/ui/button"

export function LearningUnit({ initial, catalog }: { initial: EvidenceKey; catalog: Catalog }) {
  const [target, setTarget] = useState(initial)
  const [units, setUnits] = useState<UnitAccess[] | null>(null)
  const [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const alive = useRef(true), session = useRef(sessionStorage.getItem("token"))
  const request = useRef<{ key: string; id: string } | null>(null)
  const current = () => alive.current && session.current === sessionStorage.getItem("token")
  const same = (a: EvidenceKey, b: EvidenceKey) => a.capability_id === b.capability_id && a.difficulty === b.difficulty && a.background_id === b.background_id
  const unit = units?.find(item => same(item.target, target))
  function describe(key: EvidenceKey) { return `${catalog.domains.flatMap(d => d.capabilities).find(c => c.id === key.capability_id)?.title ?? key.capability_id} · ${key.difficulty} · ${catalog.backgrounds.find(b => b.id === key.background_id)?.name ?? key.background_id}` }
  async function read() {
    setBusy(true); setError("")
    try {
      const [access, model] = await Promise.all([CapabilitiesService.readUnits(), ModelconfigService.readConfig()])
      if (current()) { setUnits(access.data); setConfig(model.data?.version ? model.data : null); setAccepted(false) }
    } catch { if (current()) setError("前置状态或模型配置读取失败；保留原目标，请重试。这不是基础不足。") }
    finally { if (current()) setBusy(false) }
  }
  useEffect(() => { alive.current = true; void read(); return () => { alive.current = false } }, [])
  function select(key: EvidenceKey) { setTarget(key); setAccepted(false); setError("") }
  async function open() {
    setBusy(true); setError("")
    try {
      const { data } = await CapabilitiesService.openLearningUnit({ body: { target, catalog_version: catalog.version } })
      if (current() && data?.target?.capability_id) setUnits(old => old?.map(item => same(item.target, data.target) ? data : item) ?? [data])
    } catch { if (current()) { setError("本次未确认解锁；请重新读取真实缺项，已有入口保留。"); } }
    finally { if (current()) setBusy(false) }
  }
  async function start(mode: "practice" | "independent") {
    if (!config?.version || !accepted || busy) return
    setBusy(true); setError("")
    const key = JSON.stringify({ target, mode, version: config.version, initial })
    if (request.current?.key !== key) request.current = { key, id: crypto.randomUUID() }
    try {
      const { data } = await CapabilitiesService.startTarget({ body: { request_id: request.current.id, target, catalog_version: catalog.version, expected_config_version: config.version, disclosure_accepted: true, mode, return_target: initial } })
      if (current() && data?.id) location.assign(`/?training_run=${data.id}`)
    } catch (failure) {
      if (current()) { const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; setError(typeof detail === "string" ? detail : "未确认开始成功；请重新读取目标状态后重试，未自动降低难度或授予证明。") }
    } finally { if (current()) setBusy(false) }
  }
  const cls = "h-auto min-h-9 max-w-full whitespace-normal"
  function missing(key: EvidenceKey) { return <li key={JSON.stringify(key)} className="space-y-1"><p>{describe(key)}</p><Button className={cls} variant="outline" disabled={busy} onClick={() => select(key)}>针对这项补练或检验</Button></li> }
  return <section aria-label="目标解锁与补基础" className="space-y-3 border p-3 break-words">
    <h3>当前目标：{describe(target)}</h3>
    <p>原目标：{describe(initial)}。未经你选择不会改变难度；缺少证明不表示不会。</p>
    {!same(target, initial) && <Button className={cls} variant="outline" disabled={busy} onClick={() => select(initial)}>返回原目标</Button>}
    <Button className={cls} variant="outline" disabled={busy} onClick={() => void read()}>重新核对前置与模型</Button>
    {error && <p role="alert">{error}</p>}
    {unit && <>
      <p>{unit.opened ? "这个学习单元已经开放；前置后来待巩固也保留入口。" : unit.eligible ? "当前前置条件已满足，可明确打开学习单元。" : "尚不能打开新学习单元，请选择下面实际缺失的证明。"}</p>
      {!unit.opened && !!unit.missing_required.length && <div><p>以下全部必需：</p><ul>{unit.missing_required.map(missing)}</ul></div>}
      {!unit.opened && unit.missing_alternatives.map((group, i) => <div key={i}><p>缺失替代组 {i + 1}：本组任选一项；各组分别满足。</p><ul>{group.map(missing)}</ul></div>)}
      {!unit.opened && unit.eligible && <Button className={cls} disabled={busy} onClick={() => void open()}>打开这个学习单元</Button>}
      <p>补练不产生独立证明。已有能力可直接检验，无需先看本题答案；仍需两个实质不同陌生案例连续独立通过，点击不会获得证明或升级。</p>
      {config?.version ? <>
        <p className="break-all">本次接收方：{config.service_url} · {config.model_id}</p>
        <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>允许发送当前目标与必要公开资料；独立检验还比较必要新旧情境及判据，不发旧作答或帮助全文。最多六次模型调用，重试可能计费，语义质量尚未验收。</span></label>
        {unit.opened && <Button className={cls} disabled={busy || !accepted} onClick={() => void start("practice")}>练习当前目标（不授予证明）</Button>}
        <Button className={cls} disabled={busy || !accepted} onClick={() => void start("independent")}>直接检验当前能力（新陌生案例）</Button>
      </> : <p>模型配置尚不可用；请保存配置后重读。已开放入口和原目标保持。</p>}
    </>}
  </section>
}
