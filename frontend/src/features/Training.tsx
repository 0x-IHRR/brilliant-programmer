import { useEffect, useRef, useState } from "react"
import { IndependentService, ModelconfigService, TrainingService, type ModelConfigPublic, type TaskPublic } from "../client"
import { type DraftProgress } from "./draftAutosave"
import { SubmissionForm } from "./SubmissionForm"
import { useRandomPreference } from "./useRandomPreference"
import { BossStandard, BossProgress } from "./Boss"
import { Button } from "../components/ui/button"

export function Training({ onLevel, openRunId = "" }: { onLevel?: (level: string) => void; openRunId?: string }) {
  const alive = useRef(true)
  const ownerSession = useRef(sessionStorage.getItem("token"))
  const current = () => alive.current && sessionStorage.getItem("token") === ownerSession.current
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const preference = useRandomPreference()
  const pendingRandom = useRef<{ key: string; request: string } | null>(null)
  const [blockedTargets, setBlockedTargets] = useState<{ capability_id: string; difficulty: string }[]>([])
  const pendingCheck = useRef<{ origin: string; version: string; request: string } | null>(null)
  const [checkAccepted, setCheckAccepted] = useState(false)
  const [config, setConfig] = useState<ModelConfigPublic | null>(null)
  const [runs, setRuns] = useState<TaskPublic[]>([])
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("training_run") ?? "")
  const selectedRef = useRef(selected)
  function selectRun(id: string) {
    selectedRef.current = id
    setSelected(id)
    const url = new URL(location.href)
    if (id) url.searchParams.set("training_run", id)
    else url.searchParams.delete("training_run")
    history.replaceState(null, "", url)
  }
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    if (openRunId && openRunId !== selectedRef.current) {
      selectRun(openRunId)
      setRefresh(n => n + 1)
    }
  }, [openRunId])
  const [panel, setPanel] = useState<DraftProgress["step"]>("materials")
  const run = runs.find(item => item.id === selected) ?? runs[0]
  const running = run && ["queued", "running", "stopping"].includes(run.status)
  useEffect(() => { setCheckAccepted(false) }, [config?.version, run?.id])
  useEffect(() => {
    let active = true
    void Promise.all([ModelconfigService.readConfig(), TrainingService.latest()]).then(async ([model, tasks]) => {
      if (!active) return
      setConfig(model.data?.version ? model.data : null)
      setAccepted(false)
      setError("")
      const missing = selected && !tasks.data.some(item => item.id === selected)
      // Current-account results do not depend on an optional historical link.
      // Keep an already loaded old round while retrying a temporary read failure.
      setRuns(items => {
        const cached = missing && items.find(item => item.id === selected)
        return cached ? [...tasks.data, cached] : tasks.data
      })
      if (!missing) return
      try {
        const saved = await TrainingService.read({ path: { run_id: selected } })
        if (!active || selectedRef.current !== selected) return
        setRuns(items => [...items.filter(item => item.id !== saved.data.id), saved.data])
      } catch (error) {
        if (!active || selectedRef.current !== selected) return
        const status = (error as { response?: { status?: number } }).response?.status
        if (status === 403 || status === 404 || status === 422) {
          setRuns(items => items.filter(item => item.id !== selected))
          selectRun("")
          setError("原轮链接不可用或不属于当前账号，已返回当前可用任务。")
        } else {
          setError("原轮暂时读取失败，当前任务与原轮链接保留；可重新读取任务与模型目的地再试。")
        }
      }
    }).catch(() => { if (active) setError("任务读取失败，已有内容保留。请重新读取实际状态。") })
    return () => { active = false }
  }, [refresh])
  useEffect(() => {
    if (!running) return
    let active = true
    const timer = window.setInterval(() => {
      void TrainingService.read({ path: { run_id: run.id } }).then(({ data }) => {
        if (active) setRuns(items => items.map(item => item.id === data.id ? data : item))
      }).catch(() => { if (active) setError("连接中断，后台任务可能仍在继续；请重新读取状态。") })
    }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [run?.id, running])
  async function act(operation: () => Promise<void>) {
    setBusy(true)
    setError("")
    try { await operation() } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === "string" ? detail : detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string" ? detail.message : "操作未确认成功；请重新读取状态，不必重复启动。")
    } finally { setBusy(false) }
  }
  const reasonLabel = (reason: string) => ({ first_basic: "首次基础无前置", needs_consolidation: "优先待巩固能力", unverified: "优先未验证能力", verified: "复习最早验证能力", seventh_day_review: "第5次推荐，复习验证已满7天的能力" } as Record<string, string>)[reason] ?? reason
  const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
  return <section aria-labelledby="training-title" className="space-y-4 break-words">
    <h2 id="training-title" className="text-xl font-semibold">随机第一关</h2>
    <p>没有正式作答时，从基础、无前置能力要求的方向选一关。不需要主题卡或入门测验。已有记录后优先待巩固、未验证能力；复习仍是普通练习，不自动产生独立证明。</p>
    <div className="space-y-2" aria-label="随机练习难度偏好">
      <label className="block">随机练习难度<select aria-label="随机练习难度" className="block w-full min-w-0 rounded border p-2" disabled={!preference.saved?.has_record} value={preference.mode} onChange={e => preference.edit(e.target.value as typeof preference.mode)}><option value="recommended">系统推荐</option><option value="基础">基础</option><option value="进阶">进阶</option><option value="综合">综合</option></select></label>
      <p>{!preference.saved ? "偏好待读取" : !preference.saved.has_record ? "首次保持基础；保存原题正式原答后可重读并选择固定难度。" : preference.ready ? "账号偏好已确认，之后新任务沿用；当前题目与草稿不变。" : "偏好尚未确认；请先保存或重读，当前题目与草稿不变。"}</p>
      <Button className={buttonClass} variant="outline" disabled={preference.busy} onClick={() => void preference.read()}>重新读取难度偏好</Button>
      <Button className={buttonClass} disabled={!preference.saved?.has_record || preference.busy || preference.conflict || preference.saved.mode === preference.mode} onClick={() => void preference.save()}>保存难度偏好</Button>
      {preference.error && <p role="alert">{preference.error}</p>}
    </div>
    <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => setRefresh(n => n + 1)}>重新读取任务与模型目的地</Button>
    {config ? <>
      <p className="break-all">本次资料接收方：{config.service_url} · {config.model_id}</p>
      <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />
        <span>允许把本次目标和必要公开资料发给此模型服务。模型会生成新案例；重试可能计费，评分可靠性未验证。</span>
      </label>
      <Button className={buttonClass} disabled={busy || !accepted || Boolean(running) || !preference.ready} onClick={() => act(async () => {
        const identity = JSON.stringify({ previous: run?.id, config: config.version, preference: preference.saved?.version })
        if (pendingRandom.current?.key !== identity) pendingRandom.current = { key: identity, request: crypto.randomUUID() }
        let data: TaskPublic
        try {
          const result = await TrainingService.start({ body: { request_id: pendingRandom.current.request, disclosure_accepted: true, expected_config_version: config.version, expected_preference_version: preference.saved?.version ?? null, previous_run_id: run?.id } })
          data = result.data
        } catch (failure) {
          const detail = (failure as { response?: { data?: { detail?: { access?: { target: { capability_id: string; difficulty: string } }[] } } } }).response?.data?.detail
          if (current()) setBlockedTargets(detail?.access?.map(item => item.target) ?? [])
          throw failure
        }
        if (!current()) return
        setBlockedTargets([])
        setRuns(items => [data, ...items.filter(item => item.id !== data.id)])
        selectRun(data.id)
        setPanel("materials")
      })}>{run ? "换个方向，主动开始新一关" : "帮我选一关"}</Button>
    </> : <p>请在账号与模型区域保存配置，再重新读取目的地。</p>}
    {error && <p role="alert">{error}</p>}
    {blockedTargets.length > 0 && <div><p>请选择原目标核对实际缺项；可补练或直接检验，不自动降低当前难度。</p>{blockedTargets.map(target => <a className="block underline" key={target.capability_id + target.difficulty} href={`/?capability=${encodeURIComponent(target.capability_id)}&difficulty=${encodeURIComponent(target.difficulty)}`}>{target.capability_id} · {target.difficulty}：核对前置与补基础</a>)}</div>}
    {runs.length > 1 && <label className="block">查看已有任务<select className="block w-full min-w-0 rounded border p-2" value={run?.id ?? ""} onChange={e => selectRun(e.target.value)}>{runs.map(item => <option key={item.id} value={item.id}>{item.goal} · {item.message}</option>)}</select></label>}
    {run && <article className="space-y-4 rounded border p-3">
      <p role="status">{run.message}</p>
      {run.boss_stage && <><BossStandard stage={run.boss_stage} /><BossProgress key={run.id} runId={run.id} onLevel={onLevel} /></>}
      {run.return_target && <a className="underline" href={`/?capability=${encodeURIComponent(run.return_target.capability_id)}&difficulty=${encodeURIComponent(run.return_target.difficulty)}`}>返回原目标并核对解锁条件</a>}
      <p>{run.target.difficulty} · 目标：{run.goal}</p>
      {run.project_simulation && <aside aria-label="项目教学来源"><strong>教学模拟</strong><p>源码不证明实际运行或事故；假设和合成日志不是生产观察。</p><p className="break-all">{run.project_simulation.repository_commit} · {run.project_simulation.module_path}</p>{run.project_materials?.map(m => <p key={m.evidence_id}>{m.evidence_id}：{({ code_excerpt: "固定源码片段", teaching_assumption: "教学假设", synthetic_log: "合成教学日志" } as Record<string, string>)[m.kind]}</p>)}<a className="underline" href={`/?project_run=${run.project_simulation.project_run_id}&project_route=${run.project_simulation.topic_id}`}>返回项目模块路线</a></aside>}
      {run.jd_simulation?.jd_document_id && <aside aria-label="JD 教学模拟来源"><strong>教学模拟</strong><p>本题不是该公司的真实架构、故障或面试题。</p><p>所选岗位：{run.jd_simulation.jd_role_name}</p><blockquote>{run.jd_simulation.requirement_quote}</blockquote><p>{run.jd_simulation.basis === "inferred" ? "推断" : "JD 明示要求"}</p><a className="underline" href={`/?jd=${run.jd_simulation.topic_id}`}>返回 JD 路线入口</a></aside>}
      {run.topic_snapshot?.version_id && <div><p>本题确认重点：{run.topic_snapshot.focus}</p><p className="break-all">原路线版本：{run.topic_snapshot.version_id} · 节点：{run.topic_snapshot.node_id}</p><p>之后路线编辑不改写本题目标、重点或作答。</p></div>}
      {run.recommendation_reason && <p>本轮选择依据：{reasonLabel(run.recommendation_reason)}。开始时已固定目标与难度，之后偏好变更不改本题。</p>}
      <p>{run.launch_mode === "independent" ? "本轮由你主动发起独立检验；最终资格依据实际帮助与冻结作答，语义质量尚未验收。" : "本轮默认练习；普通练习通过不会自动成为独立证明。"}</p>
      {run.current_mode === "practice" && run.launch_mode === "independent" && <p>本题已转为练习，不能原题切回独立；已有修为及此前冻结的合格原答保留。</p>}
      {run.case && config && !run.boss_stage && <div className="space-y-2 border p-3">
        <p>检验自己会创建另一轮新案例，不搬走本轮作答或草稿。找不到可核验的陌生情境时明确退出。</p>
        <p className="break-all">比较接收方：{config.service_url} · {config.model_id}</p>
        <label className="flex items-start gap-2"><input type="checkbox" checked={checkAccepted} onChange={e => setCheckAccepted(e.target.checked)} /><span>允许发送必要的新旧情境与判据用于生成和陌生比较，不发送旧正式作答或帮助全文；最多六次调用，重试可能计费。</span></label>
        <Button className={buttonClass} disabled={busy || !checkAccepted || Boolean(running)} onClick={() => act(async () => {
          if (pendingCheck.current?.origin !== run.id || pendingCheck.current.version !== config.version) pendingCheck.current = { origin: run.id, version: config.version!, request: crypto.randomUUID() }
          const { data } = await IndependentService.startCheck({ path: { origin_id: run.id }, body: { request_id: pendingCheck.current.request, expected_config_version: config.version!, disclosure_accepted: true } })
          if (!current()) return
          setRuns(items => [data, ...items.filter(item => item.id !== data.id)])
          selectRun(data.id)
          setPanel("materials")
          pendingCheck.current = null
        })}>检验自己：主动新建陌生案例</Button>
        {run.current_mode === "independent" && <Button variant="outline" className={buttonClass} disabled={busy} onClick={() => act(async () => {
          const { data } = await IndependentService.convertPractice({ path: { run_id: run.id } })
          if (current()) setRuns(items => items.map(item => item.id === data.id ? data : item))
        })}>本轮改为练习（不能原题切回）</Button>}
      </div>}
      {run.launch_mode === "independent" && !run.case && ["failed", "stopped"].includes(run.status) && <Button className={buttonClass} disabled={busy} onClick={() => act(async () => {
        const { data } = await IndependentService.retryCheck({ path: { run_id: run.id } })
        if (current()) setRuns(items => items.map(item => item.id === data.id ? data : item))
      })}>重试本轮剩余步骤（预算不重置）</Button>}
      <p className="break-all">本任务目的地：{run.destination} · 模型：{run.model_id}</p>
      {running && <>
        <p>关页后本次任务继续；返回可读取进度。不会自动开始后续训练。</p>
        <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(async () => {
          const { data } = await TrainingService.stop({ path: { run_id: run.id } })
          setRuns(items => items.map(item => item.id === data.id ? data : item))
        })}>停止本次生成</Button>
        <p>停止会尝试中断在途请求，不能保证撤销执行或退费。等待服务端确认后才算生效。</p>
      </>}
      <details><summary>调用记录与用量（{run.attempts.length} 次）</summary>
        {run.attempts.map(attempt => <p key={attempt.number}>第 {attempt.number} 次 · {attempt.code} · 输入 {attempt.prompt_tokens ?? "未知"} / 输出 {attempt.completion_tokens ?? "未知"} / 总 token {attempt.total_tokens ?? "未知"}</p>)}
        <p>实际费用请查看模型服务商账单。缺失用量为未知，不表示免费；崩溃前请求可能已计费。</p>
      </details>
      {run.case && <div key={run.id} className="space-y-4">
        <h3 className="text-lg font-semibold">{run.case.title}</h3>
        <p className="whitespace-pre-wrap">{run.case.task}</p>
        <p>{run.case.quality}</p>
        <div className="flex flex-wrap gap-2 md:hidden"><Button variant="outline" onClick={() => setPanel("materials")}>材料</Button><Button variant="outline" onClick={() => setPanel("judgments")}>判断</Button><Button variant="outline" onClick={() => setPanel("coach")}>概念</Button></div>
        <div className="grid gap-4 md:grid-cols-2">
          <section aria-label="案例材料" className={`${panel === "materials" ? "block" : "hidden"} min-w-0 space-y-3 md:block`}>
            <h4 className="font-semibold">材料与假设</h4>
            {run.case.assumptions.map((item, index) => <p key={index}>{item}</p>)}
            {run.case.evidence.map(item => <div key={item.id} className="space-y-2"><p>{item.label}</p><pre className="whitespace-pre-wrap break-all font-sans">{item.text}</pre>{item.citations.map((citation, index) => <blockquote key={index} className="border-l-2 pl-2">{citation.quote}（{citation.source_id}）</blockquote>)}</div>)}
            {run.case.sources.map(source => <details key={source.id}><summary>核对来源：{source.id}</summary><a className="underline break-all" href={source.url} target="_blank" rel="noreferrer">{source.url}</a><p className="break-all">{source.version}</p><p>{source.locator}</p><pre className="whitespace-pre-wrap break-all font-sans">{source.text}</pre></details>)}
          </section>
          <section aria-label="必答判断" className="min-w-0 space-y-3">
            <h4 className="font-semibold">作判断</h4>
            <SubmissionForm boss={Boolean(run.boss_stage)} runId={run.id} caseData={run.case} config={config} panel={panel} onPanel={setPanel} />
          </section>
        </div>
      </div>}
    </article>}
  </section>
}
