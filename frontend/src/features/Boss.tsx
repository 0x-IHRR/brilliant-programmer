import { useEffect, useRef, useState } from "react"
import { BossService, ModelconfigService, type BossAccess, type BossPublic, type FirstStage, type BossStage, type ModelConfigPublic, type RevalidationPublic } from "../client"
import { Button } from "../components/ui/button"

const cls = "h-auto min-h-9 max-w-full whitespace-normal"
export function BossStandard({ stage }: { stage: FirstStage | BossStage }) {
  return <div className="space-y-2 break-words"><p>冻结标准：{stage.version} · {stage.from_level} → {stage.to_level ?? "保持最高等级，继续综合挑战"}</p><ul className="space-y-2">{stage.mandatory.map(item => <li key={item.judgment_id}>{item.scope} · 必考判断 {item.judgment_id}<br />{item.target.capability_id} · {item.target.difficulty} · {item.target.background_id}{"observations" in item && <ul>{item.observations.map(observation => <li key={observation.id}>{observation.requirement}（来源领域：{observation.source_capability}）</li>)}</ul>}</li>)}</ul><p>{stage.passing_rule}</p><p>本版只验证列出的具体背景；语义可靠性尚未通过人工样本验收。</p></div>
}

export function Boss() {
  const [opened, setOpened] = useState(() => new URLSearchParams(location.search).get("boss") === "1")
  return <section aria-label="Boss挑战入口" className="space-y-3 border p-3 break-words"><h2>阶段 Boss 与晋升</h2><p>首阶段100点，后续阶段300、700、1500、3000、6000点；无需刷完所有小关。只能按当前等级逐级挑战，修为不会自动升级；AI级仍可继续综合挑战。</p><Button className={cls} variant="outline" onClick={() => setOpened(value => !value)}>{opened ? "收起Boss入口" : "查看阶段标准与挑战资格"}</Button>{opened && <BossStart />}</section>
}

function BossStart() {
  const [access, setAccess] = useState<BossAccess | null>(null)
  const [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [selected, setSelected] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const alive = useRef(true), token = useRef(sessionStorage.getItem("token"))
  const request = useRef<{ key: string; id: string } | null>(null)
  const current = () => alive.current && token.current === sessionStorage.getItem("token")
  async function read() {
    setBusy(true); setError("")
    try {
      const [state, model] = await Promise.all([BossService.bossAccess(), ModelconfigService.readConfig()])
      if (current() && state.data?.stage?.version) { setAccess(state.data); setConfig(model.data?.version ? model.data : null); setAccepted(false) }
    } catch { if (current()) setError("挑战资格或配置未确认，原记录保留；请重新读取。") }
    finally { if (current()) setBusy(false) }
  }
  useEffect(() => { alive.current = true; void read(); return () => { alive.current = false } }, [])
  const pending = (access?.revalidations ?? []).filter(item => item.status === "required")
  const selectedRequirement = pending.find(item => item.promotion_id === selected)
  const stage = selectedRequirement?.stage ?? access?.stage
  const requiredPoints = stage?.launch_points
  const canStart = Boolean(typeof requiredPoints === "number" && access && access.points >= requiredPoints && (!selected || selectedRequirement))
  async function start() {
    if (!stage?.version || !config?.version || !accepted || busy || !canStart) return
    setBusy(true); setError("")
    const key = JSON.stringify({ stage, requirement: selectedRequirement?.current_event_id, config: config.version })
    if (request.current?.key !== key) request.current = { key, id: crypto.randomUUID() }
    try {
      const { data } = await BossService.startBoss({ body: { request_id: request.current.id, expected_stage: stage, expected_config_version: config.version, disclosure_accepted: true, revalidation_of: selectedRequirement?.promotion_id ?? null, expected_revalidation_event_id: selectedRequirement?.current_event_id ?? null } })
      if (current() && data?.id) location.assign(`/?training_run=${data.id}`)
    } catch (failure) {
      if (current()) { const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; setError(typeof detail === "string" ? detail : "挑战发起未确认，请重读原记录；未自动新建另一轮。") }
    } finally { if (current()) setBusy(false) }
  }
  return <div className="space-y-3"><Button className={cls} variant="outline" disabled={busy} onClick={() => void read()}>重新读取Boss资格与配置</Button>{error && <p role="alert">{error}</p>}{access && <><p>服务器当前等级：{access.level} · 累计修为：{access.points}</p>{pending.length > 0 && <p role="status">有{pending.length}条晋升待补验；已获等级、修为和学习入口保留。期间普通Boss可练习，但不会晋升，解除后须主动开始新挑战。</p>}{(access.revalidations ?? []).map(item => <RevalidationHistory key={item.promotion_id} item={item} />)}<label className="block">本次挑战<select aria-label="选择当前阶段或关联补验" className="block w-full max-w-full border p-2" disabled={busy} value={selected} onChange={event => { setSelected(event.target.value); setAccepted(false) }}><option value="">当前等级的阶段Boss</option>{pending.map(item => <option key={item.current_event_id} value={item.promotion_id}>补验：{item.stage.from_level} → {item.stage.to_level}</option>)}</select></label>{selected && !selectedRequirement && <p role="alert">该补验要求已解除或变化，请重新选择当前要求。</p>}{stage && <BossStandard stage={stage} />}{!canStart && stage && <p>本阶段需累计{stage.launch_points}点且补验关联仍有效；原记录保留。</p>}{config?.version && !config.revoked ? <><p className="break-all">模型接收方：{config.service_url} · {config.model_id}</p><label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)} /><span>已查看阶段标准，允许发送本阶段全部必考范围、必要公开资料与完整已见情境判据进行新题生成和比较，不发送旧正式作答或帮助全文；出题最多六次模型调用，重试可能计费。</span></label><Button className={cls} disabled={busy || !accepted || !canStart} onClick={() => void start()}>主动开始{selectedRequirement ? "关联补验" : stage?.from_level === "小白程序员" ? "首阶段" : "当前阶段"}Boss（独立新案例）</Button></> : <p>请先保存可用模型配置后重读；既有挑战记录仍可查看。</p>}<div><p>已有Boss挑战：</p>{access.run_ids.map((id, index) => <a key={id} className="block underline" href={`/?training_run=${id}`}>查看挑战记录 {access.run_ids.length - index}</a>)}</div></>}</div>
}

function RevalidationHistory({ item }: { item: RevalidationPublic }) {
  return <details className="space-y-2 border p-2"><summary>{item.stage.from_level} → {item.stage.to_level}：{item.status === "required" ? "待补验" : "补验已通过"}</summary><p>原晋升与已有等级保留；每次补验仅补足这一条晋升的证据。</p><a className="block underline" href={`/?training_run=${item.original_run_id}`}>查看原晋升及评分</a>{item.events.map(event => <p key={event.id}>记录{event.sequence} · {event.kind === "required" ? "终态复核确认缺少有效通过，要求新的同阶段补验" : "关联补验独立通过，仅解除这一条限制"} · {new Date(event.created_at).toLocaleString()}<a className="block underline" href={`/?training_run=${event.review_run_id ?? event.resolved_run_id}`}>查看对应原答与结果</a></p>)}</details>
}

export function BossProgress({ runId, onLevel }: { runId: string; onLevel?: (level: string) => void }) {
  const [value, setValue] = useState<BossPublic | null>(null)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true, terminal = false, generation = 0
    const token = sessionStorage.getItem("token")
    async function read() {
      const turn = ++generation
      try {
        const { data } = await BossService.readBoss({ path: { run_id: runId } })
        if (!active || turn !== generation || sessionStorage.getItem("token") !== token || data?.run_id !== runId) return
        setValue(data); setError(""); onLevel?.(data.current_level)
        terminal = Boolean(data.decision && data.decision.outcome !== "pending_delivery")
      } catch { if (active && turn === generation && sessionStorage.getItem("token") === token) setError("Boss结论读取失败，已有记录保留；可重新读取。") }
    }
    void read()
    const timer = window.setInterval(() => { if (!terminal) void read() }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [runId, refresh, onLevel])
  const label = (outcome: string) => ({ independent_pass_candidate: "全部必考判断与必要观察均获得有效独立通过", evidenced_fail: "本次确认了具体短板，保留原等级与历史", pending_delivery: "帮助交付尚待核实，暂不晋升", practice: "本题为练习，不计独立晋升", unclear: "尚不能确认全部判断，不记为能力失败", system_failure: "系统或规则核对未完成，不记为能力失败", invalid_case: "案例无效，不记为挑战失败", no_qualified_case: "案例尚无有效陌生资格，不晋升" } as Record<string, string>)[outcome] ?? outcome
  return <section aria-label="Boss结算与晋升" className="space-y-3 border p-3"><h3>本轮 Boss 结算</h3><Button className={cls} variant="outline" onClick={() => setRefresh(n => n + 1)}>重新读取Boss结论</Button>{error && <p role="alert">{error}</p>}{value && <><p>服务器当前等级：{value.current_level} · 累计修为：{value.points}</p>{value.promotion_id && <p role="status">本轮晋升已保存：{value.stage.from_level} → {value.stage.to_level}；重复读取或提交不再升级。</p>}{value.disposition === "blocked_revalidation" && <p role="status">本轮晋升处置已冻结为不晋升：发起或结算时存在待补验。以后解除限制也不会把本轮旧回执补作晋升；请主动开始新挑战。</p>}{value.revalidation_of && <p>本轮为关联补验，发起时真实等级：{value.launch_level}；通过只解除所关联要求，不再升级。</p>}{value.disposition === "revalidated" && <p>本轮补验通过事实已保存；该晋升的当前要求与后续复核历史如下。</p>}{value.revalidation?.promotion_id && <RevalidationHistory item={value.revalidation} />}{value.decision ? <p>{label(value.decision.outcome)}</p> : <p>尚未形成冻结的有效评分；未晋升，不表示挑战失败。</p>}{value.decision?.shortfalls?.map(item => <div key={item.judgment_id}><p>{item.judgment_id}：{item.gap}</p><a className="underline" href={`/?capability=${encodeURIComponent(item.target.capability_id)}&difficulty=${encodeURIComponent(item.target.difficulty)}`}>针对 {item.target.capability_id} 补练或主动检验</a></div>)}<p>本轮全部判断与理由完成仍沿原轮一次10点；不会因本次失败扣修为或撤销历史。语义质量尚未验收。</p><a className="underline" href="/?boss=1">返回Boss入口，查看标准或主动新题重试</a></>}</section>
}
