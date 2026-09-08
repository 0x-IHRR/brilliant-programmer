import { useEffect, useRef, useState } from "react"
import { SubmissionsService, type Answer, type ModelConfigPublic, type PublicCase, type SubmissionState, type Submit } from "../client"
import { Button } from "../components/ui/button"

export function SubmissionForm({ runId, caseData, config }: { runId: string; caseData: PublicCase; config: ModelConfigPublic | null }) {
  const [answers, setAnswers] = useState<Answer[]>(caseData.judgments.map(j => ({ judgment_id: j.id, value: j.kind === "order" ? j.options.map(() => -1) : "", reason: "" })))
  const [state, setState] = useState<SubmissionState | null>(null)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const dirty = useRef(false)
  const pending = useRef<Submit | null>(null)
  const latest = state?.submissions[state.submissions.length - 1]
  const checking = latest && ["checking", "stopping"].includes(latest.status)
  const completed = Boolean(state?.completed_at)
  const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
  const inputClass = "block w-full min-w-0 rounded border p-2 focus-visible:outline-2 focus-visible:outline-offset-2"
  useEffect(() => { setAccepted(false) }, [config?.version])
  useEffect(() => {
    let active = true
    void SubmissionsService.readSubmissions({ path: { run_id: runId } }).then(({ data }) => {
      if (!active) return
      setState(data)
      if (!dirty.current && data.submissions.length) setAnswers(data.submissions[data.submissions.length - 1].answers)
    }).catch(() => { if (active) setError("提交记录读取失败，当前输入保留。请重读后再交卷。") })
    return () => { active = false }
  }, [runId])
  useEffect(() => {
    if (!checking) return
    let active = true
    const timer = window.setInterval(() => {
      void SubmissionsService.readSubmissions({ path: { run_id: runId } }).then(({ data }) => {
        if (active) setState(data)
      }).catch(() => { if (active) setError("连接中断，检查可能继续；输入保留，请重读实际结果。") })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [runId, checking])
  function edit(judgmentId: string, update: Partial<Answer>) {
    dirty.current = true
    setAnswers(items => items.map(answer => answer.judgment_id === judgmentId ? { ...answer, ...update } : answer))
  }
  async function act(operation: () => Promise<{ data: SubmissionState }>) {
    setBusy(true); setError("")
    try { const { data } = await operation(); setState(data) }
    catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === "string" ? detail : "未确认交卷结果。当前输入保留，请重读记录或重试同一提交；不会重复发奖。")
    } finally { setBusy(false) }
  }
  return <div className="space-y-3">
    <p>每个判断和相关理由都是必填；答错仍可完成。可以用白话说不知道原因、还需要看哪份材料。不要粘贴秘密或未授权资料。</p>
    {!completed && <p>编辑中的输入尚未自动保存；点击交卷后才保存不可覆盖的提交快照。理由相关性确认前不算完成。</p>}
    <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(() => SubmissionsService.readSubmissions({ path: { run_id: runId } }))}>重新读取提交结果</Button>
    {state && <p>本轮修为：{state.awarded_points} 点 · 累计修为：{state.total_points} 点。普通练习不新增能力证明或改变独立连续计数。</p>}
    {latest && <>
      <p role="status">{latest.message}</p>
      <p className="break-all">轮次 {runId} · 提交 {latest.id} · 序号 {latest.sequence}</p>
      <details><summary>已保存原答与补充记录（{state!.submissions.length} 份）</summary>
        {state!.submissions.map(item => <div key={item.id} className="space-y-2 border-b py-2">
          <p>{item.kind === "original" ? "原始作答" : item.kind === "clarification" ? "一次许可中性补答" : "同轮补充"} · 序号 {item.sequence}</p>
          {item.answers.map(answer => <p key={answer.judgment_id} className="whitespace-pre-wrap break-all">{caseData.judgments.find(j => j.id === answer.judgment_id)?.prompt}：{Array.isArray(answer.value) ? answer.value.map(i => i + 1).join(" → ") : typeof answer.value === "number" ? caseData.judgments.find(j => j.id === answer.judgment_id)?.options[answer.value] : answer.value}；理由：{answer.reason}</p>)}
          <p className="break-all">相关性检查接收方：{item.destination} · {item.model_id}</p>
          {item.attempts.map(attempt => <p key={attempt.number}>第 {attempt.number} 次 · {attempt.code} · 输入 {attempt.prompt_tokens ?? "未知"} / 输出 {attempt.completion_tokens ?? "未知"} / 总 token {attempt.total_tokens ?? "未知"}</p>)}
        </div>)}
        <p>实际费用请查看模型服务商账单。用量缺失表示未知。</p>
      </details>
      {checking && <Button className={buttonClass} variant="outline" disabled={busy} onClick={() => act(() => SubmissionsService.stopSubmission({ path: { run_id: runId, submission_id: latest.id } }))}>停止本次相关性检查</Button>}
      {latest.can_retry && <Button className={buttonClass} disabled={busy} onClick={() => act(() => SubmissionsService.retrySubmission({ path: { run_id: runId, submission_id: latest.id } }))}>重试原提交检查（可能计费）</Button>}
    </>}
    {error && <p role="alert">{error}</p>}
    {!completed && <form className="space-y-3" onSubmit={event => {
      event.preventDefault()
      if (!config || !accepted || !state) return
      const body: Submit = { request_id: "", answers, disclosure_accepted: true, expected_config_version: config.version, previous_submission_id: latest?.id ?? null }
      const old = pending.current
      body.request_id = old && JSON.stringify({ ...old, request_id: "" }) === JSON.stringify(body) ? old.request_id : crypto.randomUUID()
      pending.current = body
      void act(() => SubmissionsService.submit({ path: { run_id: runId }, body }))
    }}>
      {caseData.judgments.map(judgment => {
        const answer = answers.find(item => item.judgment_id === judgment.id)!
        return <fieldset disabled={busy || Boolean(checking)} key={judgment.id} className="min-w-0 space-y-2 border p-2">
        <legend>{judgment.prompt}</legend>
        {judgment.kind === "choice" && judgment.options.map((option, position) => <label className="flex items-start gap-2" key={position}><input required type="radio" name={`${runId}-${judgment.id}`} checked={answer.value === position} onChange={() => edit(judgment.id, { value: position })} /><span>{option}</span></label>)}
        {judgment.kind === "order" && judgment.options.map((_, step) => <label key={step} className="block">第 {step + 1} 步<select required className={inputClass} value={(answer.value as number[])[step] < 0 ? "" : (answer.value as number[])[step]} onChange={e => edit(judgment.id, { value: (answer.value as number[]).map((value, i) => i === step ? Number(e.target.value) : value) })}><option value="">请选择顺序</option>{judgment.options.map((item, position) => <option key={position} value={position}>{item}</option>)}</select></label>)}
        {judgment.kind === "prediction" && <label className="block">你的预测<textarea required maxLength={6000} className={inputClass} value={String(answer.value)} onChange={e => edit(judgment.id, { value: e.target.value })} /></label>}
        <label className="block">这一判断的理由<textarea required maxLength={6000} className={inputClass} value={answer.reason} onChange={e => edit(judgment.id, { reason: e.target.value })} /></label>
        {latest?.relevance.find(item => item.judgment_id === judgment.id && item.status !== "related") && <p>此项理由待补充，与正确性无关。</p>}
      </fieldset>})}
      {config ? <>
        <p className="break-all">本次交卷检查接收方：{config.service_url} · {config.model_id}</p>
        <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>允许将当前公开题面和本次作答发送给此模型，仅检查理由相关性。每次最多 3 次尝试，同一提交至多 6 次；重试可能计费，可靠性未验证。</span></label>
        <Button className={buttonClass} type="submit" disabled={!state || !accepted || busy || Boolean(checking)}>{latest ? "提交同轮补充（保留原答）" : "正式交卷"}</Button>
      </> : <p>请保存模型配置并重新读取目的地后交卷；已有记录仍保留。</p>}
    </form>}
  </div>
}
