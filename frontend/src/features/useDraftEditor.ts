import { useEffect, useRef, useState } from "react"
import { DraftsService, PracticeService, SubmissionsService, type Answer, type DraftAnswer, type DraftSnapshot, type PublicCase, type SubmissionState } from "../client"
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
  const saver = useRef<DraftAutosave | null>(null)
  const active = useRef(true)
  const readGeneration = useRef(0)
  const sessionToken = useRef(sessionStorage.getItem("token"))
  const current = () => active.current && sessionToken.current === sessionStorage.getItem("token")

  function install(progress: DraftProgress, version: string | null, unsaved = false) {
    saver.current?.retire()
    const editor = new DraftAutosave(progress, version, async body => {
      // Do not let a detached editor dispatch under another account's new session.
      if (sessionToken.current !== sessionStorage.getItem("token")) throw new Error("session changed")
      const { data } = practiceHelpId ? await PracticeService.savePracticeDraft({ path: { run_id: runId, help_id: practiceHelpId }, body }) : await DraftsService.saveDraft({ path: { run_id: runId }, body })
      return data
    }, next => { if (current() && saver.current === editor) setStatus(next) }, unsaved ? null : progress)
    saver.current = editor
    setAnswers(normalized(progress.answers))
    onPanel(progress.step)
    setStatus(editor.status)
    setReady(true)
    return editor
  }
  async function read(compare = false) {
    const generation = ++readGeneration.current
    const latestRead = () => current() && generation === readGeneration.current
    try {
      const [draftResponse, submissionResponse] = await Promise.all([
        practiceHelpId ? PracticeService.readPracticeDraft({ path: { run_id: runId, help_id: practiceHelpId } }) : DraftsService.readDraft({ path: { run_id: runId } }),
        practiceHelpId ? PracticeService.readPractice({ path: { run_id: runId, help_id: practiceHelpId } }).then(result => ({ data: result.data.records })) : SubmissionsService.readSubmissions({ path: { run_id: runId } }),
      ])
      if (!latestRead()) return
      const draft = draftResponse.data?.run_id === runId ? draftResponse.data : null
      const submissions = submissionResponse.data
      if (submissions.run_id !== runId) throw new Error("different round")
      setError("")
      if (compare || saver.current) { setComparison({ draft, submissions }); return }
      setState(submissions)
      const latest = submissions.submissions[submissions.submissions.length - 1]
      const base = latest?.id ?? null
      const progress: DraftProgress = draft ? {
        step: draft.progress.step ?? "materials", answers: normalized(draft.progress.answers), based_on_submission_id: draft.progress.based_on_submission_id ?? null,
      } : { answers: latest?.answers ?? empty(), step: panel, based_on_submission_id: base }
      const editor = install(progress, draft?.version ?? null)
      if (progress.based_on_submission_id !== base) {
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
  function choose(local: boolean, fromSubmission = false) {
    if (!comparison || !saver.current) return
    const { draft, submissions } = comparison
    const latest = submissions.submissions[submissions.submissions.length - 1]
    const selected = fromSubmission ? { answers: latest?.answers, step: panel } : local ? saver.current.progress : draft?.progress
    const progress: DraftProgress = {
      answers: normalized(selected?.answers ?? latest?.answers),
      step: selected?.step ?? panel,
      based_on_submission_id: latest?.id ?? null,
    }
    install({ ...progress, answers: normalized(progress.answers) }, draft?.version ?? null, true)
    // Explicit choice is the only path that accepts a newer server base version.
    saver.current!.edit(saver.current!.progress)
    setState(submissions); setComparison(null)
  }
  return { answers, state, setState, status, ready, error, comparison, edit, flush, submitted,
    retry: () => saver.current?.retry(), read: () => read(Boolean(ready)), choose,
    localProgress: saver.current?.progress }
}
