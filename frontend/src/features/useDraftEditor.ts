import { useEffect, useRef, useState } from "react"
import { DraftsService, PracticeService, SubmissionsService, type CollectionView, type Answer, type DraftAnswer, type DraftSnapshot, type PublicCase, type SubmissionState } from "../client"
import { DraftAutosave, type DraftProgress, type SaveStatus } from "./draftAutosave"

export function useDraftEditor(runId: string, caseData: PublicCase, panel: DraftProgress["step"], onPanel: (step: DraftProgress["step"]) => void, practiceHelpId?: string) {
  const empty = (): Answer[] => caseData.judgments.map(j => ({ judgment_id: j.id, value: j.kind === "order" ? j.options.map(() => -1) : "", reason: "" }))
  function normalized(input: DraftAnswer[] = []): Answer[] {
    return empty().map(blank => {
      const answer = input.find(a => a.judgment_id === blank.judgment_id)
      if (!answer) return blank
      const value = Array.isArray(blank.value)
        ? blank.value.map((_, i) => Array.isArray(answer.value) ? (answer.value[i] ?? -1) : -1)
        : answer.value ?? ""
      return { ...answer, value, reason: answer.reason ?? "" }
    })
  }
  const [answers, setAnswers] = useState<Answer[]>(empty)
  const [state, setState] = useState<SubmissionState | null>(null)
  const [status, setStatus] = useState<SaveStatus>("idle")
  const [ready, setReady] = useState(false)
  const [error, setError] = useState("")
  const [comparison, setComparison] = useState<{ draft: DraftSnapshot | null; submissions: SubmissionState } | null>(null)
  const [collection, setCollection] = useState<CollectionView | null>(null)
  const collectionRef = useRef<CollectionView | null>(null)
  const [choosing, setChoosing] = useState(false)
  const saver = useRef<DraftAutosave | null>(null)
  const active = useRef(true)
  const readGeneration = useRef(0)
  const sessionToken = useRef(sessionStorage.getItem("token"))
  const current = () => active.current && sessionToken.current === sessionStorage.getItem("token")

  function install(progress: DraftProgress, version: string | null, unsaved = false) {
    saver.current?.retire()
    let tokens = collectionRef.current!
    const editor = new DraftAutosave(progress, version, async body => {
      // Do not let a detached editor dispatch under another account's new session.
      if (sessionToken.current !== sessionStorage.getItem("token")) throw new Error("session changed")
      const request = { ...body, observed_revision: tokens.revision, generation: tokens.generation }
      const { data } = practiceHelpId ? await PracticeService.savePracticeDraft({ path: { run_id: runId, help_id: practiceHelpId }, body: request }) : await DraftsService.saveDraft({ path: { run_id: runId }, body: request })
      tokens = { ...tokens, revision: data.revision, generation: data.generation, current: data.version, versions: [...tokens.versions.filter(v => v.version !== data.version), data] }
      if (current() && saver.current === editor) { collectionRef.current = tokens; setCollection(tokens) }
      return data
    }, next => { if (current() && saver.current === editor) setStatus(next) }, unsaved ? null : progress)
    saver.current = editor
    setAnswers(normalized(progress.answers))
    onPanel(progress.step)
    setStatus(editor.status)
    setReady(true)
    return editor
  }
  async function fetchVersions() {
    return practiceHelpId ? (await PracticeService.readPracticeVersions({ path: { run_id: runId, help_id: practiceHelpId } })).data : (await DraftsService.readVersions({ path: { run_id: runId } })).data
  }
  async function read(compare = false) {
    const generation = ++readGeneration.current
    const latestRead = () => current() && generation === readGeneration.current
    try {
      const [draftResponse, submissionResponse, versions] = await Promise.all([
        practiceHelpId ? PracticeService.readPracticeDraft({ path: { run_id: runId, help_id: practiceHelpId } }) : DraftsService.readDraft({ path: { run_id: runId } }),
        practiceHelpId ? PracticeService.readPractice({ path: { run_id: runId, help_id: practiceHelpId } }).then(result => ({ data: result.data.records })) : SubmissionsService.readSubmissions({ path: { run_id: runId } }),
        fetchVersions(),
      ])
      if (!latestRead()) return
      if (draftResponse.data?.run_id && draftResponse.data.run_id !== runId) throw new Error("different round")
      const draft = versions.versions.find(v => v.version === versions.current) ?? null
      const submissions = submissionResponse.data
      if (submissions.run_id !== runId) throw new Error("different round")
      setError("")
      if (versions.run_id !== runId || (versions.help_id || null) !== (practiceHelpId || null)) throw new Error("different draft scope")
      collectionRef.current = versions; setCollection(versions)
      if (compare || saver.current) { setComparison({ draft, submissions }); return }
      setState(submissions)
      const latest = submissions.submissions[submissions.submissions.length - 1]
      const base = latest?.id ?? null
      const progress: DraftProgress = draft ? {
        step: draft.progress.step ?? "materials", answers: normalized(draft.progress.answers), based_on_submission_id: draft.progress.based_on_submission_id ?? null,
      } : { answers: latest?.answers ?? empty(), step: panel, based_on_submission_id: base }
      const editor = install(progress, draft?.version ?? null)
      if (progress.based_on_submission_id !== base || versions.unresolved.length > 0) {
        editor.markConflict()
        setComparison({ draft, submissions })
      }
    } catch { if (latestRead()) setError("草稿或提交记录读取失败，当前输入保留；请重试读取后再编辑。") }
  }
  useEffect(() => {
    active.current = true
    void read()
    const leave = () => {
      const editor = saver.current
      if (editor?.status === "failed") void editor.retry()
      else void editor?.flush()
    }
    const visibility = () => { if (document.visibilityState === "hidden") leave() }
    const online = () => { void saver.current?.retry() }
    window.addEventListener("pagehide", leave)
    window.addEventListener("online", online)
    document.addEventListener("visibilitychange", visibility)
    return () => {
      leave(); active.current = false
      readGeneration.current++
      window.removeEventListener("pagehide", leave)
      window.removeEventListener("online", online)
      document.removeEventListener("visibilitychange", visibility)
    }
  }, [runId, practiceHelpId])
  useEffect(() => {
    const editor = saver.current
    if (ready && editor && editor.progress.step !== panel) editor.edit({ ...editor.progress, step: panel })
  }, [panel, ready])
  function edit(id: string, update: Partial<Answer>) {
    const editor = saver.current
    if (!editor) return
    const next = normalized(editor.progress.answers).map(a => a.judgment_id === id ? { ...a, ...update } : a)
    setAnswers(next)
    editor.edit({ ...editor.progress, answers: next })
  }
  async function flush() {
    await saver.current?.flush()
    if (saver.current?.status === "conflict") throw new Error("请先比较冲突草稿，当前输入保留")
  }
  function submitted(data: SubmissionState) {
    setState(data)
    const editor = saver.current
    const base = data.submissions[data.submissions.length - 1]?.id ?? null
    if (editor && base !== editor.progress.based_on_submission_id) {
      const progress = { ...editor.progress, based_on_submission_id: base }
      install(progress, editor.savedVersion, true)
      saver.current!.edit(progress)
    }
  }
  async function chooseVersion(version: string) {
    const known = collectionRef.current
    if (!known || choosing) return
    setChoosing(true); setError("")
    try {
      const body = { version, observed_revision: known.revision }
      const { data } = practiceHelpId ? await PracticeService.choosePracticeDraft({ path: { run_id: runId, help_id: practiceHelpId }, body }) : await DraftsService.chooseDraft({ path: { run_id: runId }, body })
      if (!current()) return
      const selected = data.versions.find(v => v.version === data.current)
      if (!selected) throw new Error("missing selected version")
      collectionRef.current = data; setCollection(data)
      const editor = install({ ...selected.progress, step: selected.progress.step ?? "materials", answers: normalized(selected.progress.answers), based_on_submission_id: selected.progress.based_on_submission_id ?? null }, selected.version)
      const submissions = comparison?.submissions ?? state
      setState(submissions)
      const latest = submissions?.submissions[submissions.submissions.length - 1]?.id ?? null
      if ((selected.progress.based_on_submission_id ?? null) !== latest) { editor.markConflict(); setError("所选旧草稿完整保留；正式提交已更新，请从最新提交开始补充，不能改写原答。") }
      else setComparison(null)
    } catch { if (current()) { setError("选择未确认成功或版本集合已变化；输入保留，请重新读取全部版本。"); saver.current?.markConflict() } }
    finally { if (current()) setChoosing(false) }
  }
  async function choose(local: boolean, fromSubmission = false) {
    if (!comparison || !saver.current || choosing) return
    const known = collectionRef.current!
    if (!local && !fromSubmission) {
      if (known.current) await chooseVersion(known.current)
      else setError("服务端当前没有已选草稿；请选择列表中的保留版本，或明确保存本机输入。")
      return
    }
    // Preserve local input as another server version first. Choosing it requires
    // a separate click after the complete server collection has been displayed.
    setChoosing(true); setError("")
    try {
      const latest = comparison.submissions.submissions[comparison.submissions.submissions.length - 1]
      const progress = fromSubmission ? { answers: normalized(latest?.answers), step: panel, based_on_submission_id: latest?.id ?? null } : saver.current.progress
      const body = { request_id: crypto.randomUUID(), expected_version: saver.current.savedVersion, progress, observed_revision: known.revision, generation: known.generation }
      try {
        if (practiceHelpId) await PracticeService.savePracticeDraft({ path: { run_id: runId, help_id: practiceHelpId }, body })
        else await DraftsService.saveDraft({ path: { run_id: runId }, body })
      } catch (failure) {
        if ((failure as { response?: { status?: number } }).response?.status !== 409) throw failure
      }
      if (!current()) return
      await read(true)
      setError("请在服务端版本列表核对完整答案和步骤后，明确选择要继续的版本；未保存成功的本机内容不能视为已恢复。")
    } catch { if (current()) setError("未确认本机版本已保存，当前输入保留；请重读核对后重试。") }
    finally { if (current()) setChoosing(false) }
  }
  async function remove() {
    const known = collectionRef.current
    if (!known?.current || choosing || !window.confirm("仅删除指定的当前草稿？其他冲突版本、正式作答、帮助和已有修为保留。未保存的本机输入不会自动恢复。")) return
    const retained = saver.current?.progress
    saver.current?.retire(); setChoosing(true); setError("")
    try {
      const body = { observed_revision: known.revision, version: known.current }
      const { data } = practiceHelpId ? await PracticeService.deletePracticeDraft({ path: { run_id: runId, help_id: practiceHelpId }, body }) : await DraftsService.deleteDraft({ path: { run_id: runId }, body })
      if (!current()) return
      collectionRef.current = data; setCollection(data)
      const latest = state?.submissions[state.submissions.length - 1]
      const editor = install({ answers: empty(), step: "materials", based_on_submission_id: latest?.id ?? null }, null, true)
      setComparison({ draft: null, submissions: state! })
      if (data.unresolved.length) editor.markConflict()
      setError("指定当前草稿已删除；其他版本与正式历史保留。旧设备输入不会自动写回。")
    } catch { if (current()) { if (retained) install(retained, known.current, true).markConflict(); setError("删除未确认成功或当前版本已变化；输入保留，请重新读取后再决定。") } }
    finally { if (current()) setChoosing(false) }
  }
  return { answers, state, setState, status, ready, error, comparison, collection, choosing, chooseVersion, remove, edit, flush, submitted,
    retry: () => saver.current?.retry(), read: () => read(Boolean(ready)), choose,
    localProgress: saver.current?.progress }
}
