import { DraftVersions } from "./DraftVersions"
import { useEffect, useRef, useState } from "react"
import { SubmissionsService, type DraftAnswer, type ModelConfigPublic, type PublicCase, type SubmissionState, type Submit } from "../client"
import { useDraftEditor } from "./useDraftEditor"
import { type DraftProgress } from "./draftAutosave"
import { ConceptCoach } from "./ConceptCoach"
import { Evaluation } from "./Evaluation"
import { Button } from "../components/ui/button"

export function SubmissionForm({ runId, caseData, config, panel, onPanel, boss = false }: { boss?: boolean; runId: string; caseData: PublicCase; config: ModelConfigPublic | null; panel: DraftProgress["step"]; onPanel: (step: DraftProgress["step"]) => void }) {
  const draft = useDraftEditor(runId, caseData, panel, onPanel)
  const { answers, state, setState } = draft
  const [accepted, setAccepted] = useState(false)
  const [reviewAllowed, setReviewAllowed] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const pending = useRef<Submit | null>(null)
  const latest = state?.submissions[state.submissions.length - 1]
  const checking = latest && ["checking", "stopping"].includes(latest.status)
  const completed = Boolean(state?.completed_at)
  const buttonClass = "h-auto min-h-9 max-w-full whitespace-normal"
  const inputClass = "block w-full min-w-0 rounded border p-2 focus-visible:outline-2 focus-visible:outline-offset-2"
  useEffect(() => { setAccepted(false) }, [config?.version])
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
  const edit = draft.edit
  async function act(operation: () => Promise<{ data: SubmissionState }>) {
    setBusy(true); setError("")
    try { const { data } = await operation(); setState(data) }
    catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === "string" ? detail : "未确认交卷结果。当前输入保留，请重读记录或重试同一提交；不会重复发奖。")
    } finally { setBusy(false) }
  }
  function preview(items: DraftAnswer[] = []) {
    return caseData.judgments.map(j => {
      const answer = items.find(item => item.judgment_id === j.id)
      const value = answer?.value
      const text = Array.isArray(value) ? value.map(i => i < 0 ? "未选择" : j.options[i]).join(" → ") : typeof value === "number" ? j.options[value] : value || "尚未作答"
      return <p key={j.id} className="whitespace-pre-wrap break-words">{j.prompt}：{text}；理由：{answer?.reason || "尚未填写"}</p>
    })
  }
  return <div className="space-y-3">
    <div className="space-y-2" aria-label="草稿保存状态">
      <p role="status">{!draft.ready ? "正在读取已保存进度" : ({ idle: "尚无已保存草稿", saving: "草稿保存中", saved: "草稿已保存", failed: "草稿保存失败，当前输入保留", conflict: "草稿版本冲突，当前输入保留，未覆盖其他版本" })[draft.status]}</p>
      {draft.error && <p role="alert">{draft.error}</p>}
      {draft.status === "failed" && <Button variant="outline" className={buttonClass} onClick={() => void draft.retry()}>重试保存草稿</Button>}
      {(!draft.ready || draft.status === "conflict") && <Button variant="outline" className={buttonClass} onClick={() => void draft.read()}>读取草稿并比较</Button>}
    <DraftVersions collection={draft.collection} expanded={Boolean(draft.comparison)} caseData={caseData} busy={draft.choosing || busy} choose={draft.chooseVersion} remove={draft.remove} read={draft.read} />
      {draft.comparison && <div className="space-y-2 border p-2">
        <p>请选择后再继续。不会自动合并；其他设备此后再保存仍会触发新冲突。</p>
        <details open><summary>本机未保存输入</summary>{preview(draft.localProgress?.answers)}</details>
        <details open><summary>服务端已保存草稿</summary>{preview(draft.comparison.draft?.progress.answers)}</details>
        <details><summary>当前正式提交记录</summary>{draft.comparison.submissions.submissions.map(s => <div key={s.id}>{preview(s.answers)}</div>)}</details>
        <Button className={buttonClass} onClick={() => draft.choose(true)}>保留本机输入，按已读版本继续保存</Button>
        <Button variant="outline" className={buttonClass} onClick={() => draft.choose(false)}>使用已读服务端草稿</Button>
        {draft.comparison.submissions.submissions.length > 0 && <Button variant="outline" className={buttonClass} onClick={() => draft.choose(false, true)}>从最新提交记录开始补充</Button>}
      </div>}
    </div>
    <div data-training-panel="judgments" className={`${panel === "judgments" ? "block" : "hidden"} max-h-[65vh] space-y-3 overflow-y-auto overscroll-contain md:block md:max-h-none md:overflow-visible`}>
    <p>每个判断和相关理由都是必填；答错仍可完成。可以用白话说不知道原因、还需要看哪份材料。不要粘贴秘密或未授权资料。</p>
    {!completed && <p>草稿保存与交卷分开：停输 1 秒自动保存；离开时尝试保存。未成功保存的末尾输入不保证恢复。保存不评分或发放修为。</p>}
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
    {completed && reviewAllowed && <Button className={buttonClass} variant="outline" onClick={() => setReviewing(value => !value)}>{reviewing ? "收起复盘补充" : "编辑复盘补充"}</Button>}
    {(!completed || reviewing) && <form className="space-y-3" onSubmit={event => {
      event.preventDefault()
      if (!config || !accepted || !state || draft.choosing) return
      const body: Submit = { request_id: "", answers, disclosure_accepted: true, evaluate_after_submit: !completed, expected_config_version: config.version, previous_submission_id: latest?.id ?? null }
      const old = pending.current
      body.request_id = old && JSON.stringify({ ...old, request_id: "" }) === JSON.stringify(body) ? old.request_id : crypto.randomUUID()
      pending.current = body
      void act(async () => {
        await draft.flush()
        const result = await SubmissionsService.submit({ path: { run_id: runId }, body })
        draft.submitted(result.data)
        return result
      })
    }}>
      {caseData.judgments.map(judgment => {
        const answer = answers.find(item => item.judgment_id === judgment.id)!
        return <fieldset disabled={!draft.ready || draft.choosing || busy || Boolean(checking)} key={judgment.id} className="min-w-0 space-y-2 border p-2">
        <legend>{judgment.prompt}</legend>
        {judgment.kind === "choice" && judgment.options.map((option, position) => <label className="flex items-start gap-2" key={position}><input required type="radio" name={`${runId}-${judgment.id}`} checked={answer.value === position} onChange={() => edit(judgment.id, { value: position })} /><span>{option}</span></label>)}
        {judgment.kind === "order" && judgment.options.map((_, step) => <label key={step} className="block">第 {step + 1} 步<select required className={inputClass} value={(answer.value as number[])[step] < 0 ? "" : (answer.value as number[])[step]} onChange={e => edit(judgment.id, { value: (answer.value as number[]).map((value, i) => i === step ? Number(e.target.value) : value) })}><option value="">请选择顺序</option>{judgment.options.map((item, position) => <option key={position} value={position}>{item}</option>)}</select></label>)}
        {judgment.kind === "prediction" && <label className="block">你的预测<textarea aria-label="你的预测" required maxLength={6000} className={inputClass} value={String(answer.value)} onChange={e => edit(judgment.id, { value: e.target.value })} /></label>}
        <label className="block">这一判断的理由<textarea aria-label="这一判断的理由" required maxLength={6000} className={inputClass} value={answer.reason} onChange={e => edit(judgment.id, { reason: e.target.value })} /></label>
        {latest?.relevance.find(item => item.judgment_id === judgment.id && item.status !== "related") && <p>此项理由待补充，与正确性无关。</p>}
      </fieldset>})}
      {config ? <>
        <p className="break-all">本次交卷检查接收方：{config.service_url} · {config.model_id}</p>
        <label className="flex items-start gap-2"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} /><span>{completed ? "保存本轮复盘补充，保留原答及冻结评分；不再次调用模型、评分或奖励。" : "允许将当前公开题面与作答发送给此模型检查相关性；完成后继续发送当前冻结题、来源、原答及一次许可补答，逐项生成简短反馈。每次最多 3 次尝试，同一提交至多 6 次；重试可能计费，可靠性未验证。"}</span></label>
        <Button className={buttonClass} type="submit" disabled={!state || !draft.ready || draft.choosing || draft.status === "conflict" || !accepted || busy || Boolean(checking)}>{completed ? "保存复盘补充（不重评）" : latest ? "提交同轮补充（保留原答）" : "正式交卷"}</Button>
      </> : <p>请保存模型配置并重新读取目的地后交卷；已有记录仍保留。</p>}
    </form>}
    <Evaluation boss={boss} runId={runId} caseData={caseData} config={config} submitted={completed} onFrozen={setReviewAllowed} />
    </div>
    <div data-training-panel="coach" className={`${panel === "coach" ? "block" : "hidden"} max-h-[65vh] overflow-y-auto overscroll-contain md:block md:max-h-none md:overflow-visible`}><ConceptCoach key={runId} runId={runId} answers={answers} config={config} /></div>
  </div>
}
