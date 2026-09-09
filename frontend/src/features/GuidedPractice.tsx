import { useEffect, useRef, useState } from "react"
import { PracticeService, type ModelConfigPublic, type PracticeState, type Submit } from "../client"
import { Button } from "../components/ui/button"
import { useDraftEditor } from "./useDraftEditor"
import { type DraftProgress } from "./draftAutosave"

export function GuidedPractice({ runId, helpId, config }: { runId: string; helpId: string; config: ModelConfigPublic | null }) {
  const [value, setValue] = useState<PracticeState | null>(null)
  const [error, setError] = useState("")
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    const token = sessionStorage.getItem("token")
    void PracticeService.readPractice({ path: { run_id: runId, help_id: helpId } }).then(({ data }) => {
      if (active && token === sessionStorage.getItem("token") && data.help_id === helpId) { setValue(data); setError("") }
    }).catch(() => { if (active) setError("跟练读取失败，未修改原题；可以重试。") })
    return () => { active = false }
  }, [runId, helpId, refresh])
  return <section aria-label="示范后小练习" className="space-y-3 border-t pt-3 min-w-0">
    <h5 className="font-semibold">你来做一个小练习</h5>
    {error && <><p role="alert">{error}</p><Button variant="outline" onClick={() => setRefresh(n => n + 1)}>重读小练习</Button></>}
    {value && <PracticeEditor key={`${runId}:${helpId}:${value.exercise.case.judgments[0].id}`} runId={runId} helpId={helpId} initial={value} config={config} />}
  </section>
}

function PracticeEditor({ runId, helpId, initial, config }: { runId: string; helpId: string; initial: PracticeState; config: ModelConfigPublic | null }) {
  const [panel, setPanel] = useState<DraftProgress["step"]>("judgments")
  const draft = useDraftEditor(runId, initial.exercise.case, panel, setPanel, helpId)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const active = useRef(true), token = useRef(sessionStorage.getItem("token"))
  const pending = useRef<Submit | null>(null)
  const current = () => active.current && token.current === sessionStorage.getItem("token")
  const latest = draft.state?.submissions[draft.state.submissions.length - 1]
  const checking = latest && ["checking", "stopping"].includes(latest.status)
  const completed = Boolean(draft.state?.submissions.some(s => s.status === "completed"))
  const path = { run_id: runId, help_id: helpId }
  const cls = "h-auto min-h-9 max-w-full whitespace-normal"
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => { setAccepted(false) }, [config?.version])
  useEffect(() => {
    if (!checking) return
    let alive = true
    const timer = setInterval(() => {
      void PracticeService.readPractice({ path }).then(({ data }) => { if (alive && current()) draft.setState(data.records) }).catch(() => { if (alive && current()) setError("跟练连接中断，检查可能继续；输入保留，请重读。") })
    }, 1000)
    return () => { alive = false; clearInterval(timer) }
  }, [checking, helpId, runId])
  async function act(operation: () => Promise<{ data: PracticeState }>, submitted = false) {
    setBusy(true); setError("")
    try { const { data } = await operation(); if (current() && data.help_id === helpId) { if (submitted) draft.submitted(data.records); else draft.setState(data.records) } }
    catch (failure) { if (current()) { const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; setError(typeof detail === "string" ? detail : "操作未确认成功；输入保留，请重读或重试原请求。") } }
    finally { if (current()) setBusy(false) }
  }
  const preview = (answers: { judgment_id: string; value?: unknown; reason?: string }[] = []) => answers.map(a => <p key={a.judgment_id} className="whitespace-pre-wrap">判断：{JSON.stringify(a.value)}；理由：{a.reason || "尚未填写"}</p>)
  return <div className="space-y-3 min-w-0">
    <p>{initial.exercise.instructions}</p>
    <p>只看示范不发奖励；本轮原题与跟练合计一次 10 点。原题答案与跟练分别保存。</p>
    <p role="status">{!draft.ready ? "正在读取跟练草稿" : ({ idle: "尚无已保存跟练草稿", saving: "跟练草稿保存中", saved: "跟练草稿已保存", failed: "跟练草稿保存失败，输入保留", conflict: "跟练草稿冲突，输入保留" })[draft.status]}</p>
    <p>停输 1 秒自动保存，离开时尝试保存；未保存的最后输入不保证恢复。保存不交卷或发奖。</p>
    {(error || draft.error) && <p role="alert">{error || draft.error}</p>}
    {draft.status === "failed" && <Button className={cls} variant="outline" onClick={() => void draft.retry()}>重试跟练草稿</Button>}
    {(!draft.ready || draft.status === "conflict") && <Button className={cls} variant="outline" onClick={() => void draft.read()}>读取跟练草稿并比较</Button>}
    {draft.comparison && <div className="space-y-2 border p-2">
      <p>本机输入</p>{preview(draft.localProgress?.answers)}<p>服务端草稿</p>{preview(draft.comparison.draft?.progress.answers)}
      <Button className={cls} onClick={() => draft.choose(true)}>保留本机跟练输入</Button>
      <Button className={cls} variant="outline" onClick={() => draft.choose(false)}>使用服务端跟练草稿</Button>
      {draft.comparison.submissions.submissions.length > 0 && <Button className={cls} variant="outline" onClick={() => draft.choose(false, true)}>从最新跟练提交继续</Button>}
    </div>}
    {latest && <p role="status">{latest.message}</p>}
    {draft.state && <p>本轮修为：{draft.state.awarded_points} 点。{completed ? "跟练已完成，完成不表示独立掌握。" : "跟练尚未完成。"}</p>}
    <Button className={cls} variant="outline" disabled={busy} onClick={() => void act(() => PracticeService.readPractice({ path }))}>重读跟练结果</Button>
    {checking && <Button className={cls} variant="outline" disabled={busy} onClick={() => void act(() => PracticeService.stopPractice({ path: { ...path, submission_id: latest.id } }))}>停止跟练检查</Button>}
    {latest?.can_retry && <Button className={cls} disabled={busy} onClick={() => void act(() => PracticeService.retryPractice({ path: { ...path, submission_id: latest.id } }))}>重试跟练检查（可能计费）</Button>}
    <form className="space-y-3" onSubmit={event => {
      event.preventDefault()
      if (!draft.state || (!completed && (!config || !accepted))) return
      const body: Submit = { request_id: "", answers: draft.answers, expected_config_version: config?.version ?? latest!.config_version, disclosure_accepted: accepted, previous_submission_id: latest?.id ?? null }
      body.request_id = pending.current && JSON.stringify({ ...pending.current, request_id: "" }) === JSON.stringify(body) ? pending.current.request_id : crypto.randomUUID()
      pending.current = body
      void act(async () => { await draft.flush(); return PracticeService.submitPractice({ path, body }) }, true)
    }}>
      {initial.exercise.case.judgments.map(j => {
        const answer = draft.answers.find(a => a.judgment_id === j.id)!
        return <fieldset key={j.id} disabled={!draft.ready || busy || Boolean(checking)} className="space-y-2 min-w-0"><legend>{j.prompt}</legend>
          {j.kind === "choice" && j.options.map((text, i) => <label key={i} className="flex gap-2 items-start"><input required type="radio" name={`practice-${helpId}-${j.id}`} checked={answer.value === i} onChange={() => draft.edit(j.id, { value: i })} />{text}</label>)}
          {j.kind === "order" && j.options.map((_, i) => <label key={i} className="block">跟练第{i + 1}步<select className="block max-w-full border p-2" required value={(answer.value as number[])[i] < 0 ? "" : (answer.value as number[])[i]} onChange={e => draft.edit(j.id, { value: (answer.value as number[]).map((v, n) => n === i ? Number(e.target.value) : v) })}><option value="">请选择</option>{j.options.map((text, n) => <option key={n} value={n}>{text}</option>)}</select></label>)}
          {j.kind === "prediction" && <label>跟练预测<textarea required className="block w-full border p-2" maxLength={6000} value={String(answer.value)} onChange={e => draft.edit(j.id, { value: e.target.value })} /></label>}
          <label className="block">我的跟练理由<textarea aria-label="我的跟练理由" required className="block w-full min-w-0 border p-2" maxLength={6000} value={answer.reason} onChange={e => draft.edit(j.id, { reason: e.target.value })} /></label>
        </fieldset>
      })}
      {!completed && config && <><p className="break-all">跟练检查接收方：{config.service_url} · {config.model_id}</p><label className="flex gap-2 items-start"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />允许发送当前小练习题面和本次判断、理由，检查相关性；重试可能计费，不评分独立掌握。</label></>}
      {!completed && !config && <p>请保存并重新读取模型配置；已有草稿和记录保留。</p>}
      <Button type="submit" className={cls} disabled={!draft.ready || busy || Boolean(checking) || draft.status === "conflict" || (!completed && (!accepted || !config))}>{completed ? "保存跟练复盘（不重评）" : "提交我的小练习"}</Button>
    </form>
    <details><summary>跟练原答与用量</summary>{draft.state?.submissions.map(s => <div key={s.id} className="border-t py-2">{preview(s.answers)}<p>提交序号 {s.sequence}</p>{s.attempts.map(a => <p key={a.number}>第{a.number}次 · {a.code} · 输入{a.prompt_tokens ?? "未知"} / 输出{a.completion_tokens ?? "未知"} / 总token{a.total_tokens ?? "未知"}</p>)}</div>)}</details>
  </div>
}
