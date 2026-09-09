import { useEffect, useRef, useState } from "react"
import { TrainingService, type PreferencePublic } from "../client"

type Mode = PreferencePublic["mode"]
export function useRandomPreference() {
  const [saved, setSaved] = useState<PreferencePublic | null>(null)
  const [mode, setMode] = useState<Mode>("recommended")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [conflict, setConflict] = useState(false)
  const alive = useRef(true), generation = useRef(0), edits = useRef(0)
  const owner = useRef(sessionStorage.getItem("token"))
  const current = () => alive.current && owner.current === sessionStorage.getItem("token")
  async function read() {
    const request = ++generation.current, editing = edits.current
    setBusy(true)
    try {
      const { data } = await TrainingService.readPreference()
      if (!current() || request !== generation.current) return
      setSaved(data)
      if (editing === edits.current) setMode(data.mode)
      setConflict(false); setError("")
    } catch { if (current() && request === generation.current) setError("难度偏好读取失败，保留当前选择，请重试。") }
    finally { if (current() && request === generation.current) setBusy(false) }
  }
  useEffect(() => { alive.current = true; void read(); return () => { alive.current = false; generation.current++ } }, [])
  async function save() {
    if (!saved || busy || conflict) return
    const request = ++generation.current, editing = edits.current, selected = mode
    setBusy(true); setError("")
    try {
      const { data } = await TrainingService.savePreference({ body: { expected_version: saved.version, mode: selected } })
      if (!current() || request !== generation.current) return
      setSaved(data)
      if (editing === edits.current) setMode(data.mode)
    } catch (failure) {
      if (current() && request === generation.current) {
        const status = (failure as { response?: { status?: number } }).response?.status
        setConflict(status === 409)
        setError(status === 409 ? "另一设备已修改偏好，请重读后重新选择；当前题和输入不变。" : "偏好未确认保存，保留当前选择；请重读确认或重试。")
      }
    } finally { if (current() && request === generation.current) setBusy(false) }
  }
  return { saved, mode, busy, error, conflict, ready: Boolean(saved) && !busy && !conflict && saved?.mode === mode, read, save, edit(value: Mode) { edits.current++; setMode(value) } }
}
