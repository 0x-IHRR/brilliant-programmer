// One editor instance belongs to one run. The future SDK adapter supplies save;
// this module never submits, calls a model, or stores credentials/browser data.
export type DraftProgress = {
  answers: { judgment_id: string; value: number | number[] | string | null; reason: string }[]
  step: "materials" | "judgments" | "coach"
  based_on_submission_id: string | null
}
export type DraftWrite = { request_id: string; expected_version: string | null; progress: DraftProgress }
export type SaveStatus = "idle" | "saving" | "saved" | "failed" | "conflict"

type Save = (request: DraftWrite) => Promise<{ version: string; request_id: string }>

export class DraftAutosave {
  status: SaveStatus
  private desired: DraftProgress
  private saved: DraftProgress | null
  private pending: DraftWrite | null = null
  private timer: ReturnType<typeof setTimeout> | undefined
  private flight: Promise<void> | null = null
  private due = 0
  private flushAfterFlight = false

  constructor(
    progress: DraftProgress,
    private version: string | null,
    private save: Save,
    private changed: (status: SaveStatus) => void,
  ) {
    this.desired = structuredClone(progress)
    this.saved = version ? structuredClone(progress) : null
    this.status = version ? "saved" : "idle"
  }

  get progress() { return structuredClone(this.desired) }

  private setStatus(status: SaveStatus) { this.status = status; this.changed(status) }
  private dirty() { return JSON.stringify(this.desired) !== JSON.stringify(this.saved) }
  private schedule() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => { void this.flush() }, Math.max(0, this.due - Date.now()))
  }

  edit(progress: DraftProgress) {
    this.desired = structuredClone(progress)
    this.due = Date.now() + 1000
    // A flush queued for older input must not bypass this edit's debounce.
    this.flushAfterFlight = false
    // Failed/unknown requests must be reconciled with their original identity.
    // Conflict resolution is explicit; further typing cannot silently pick a winner.
    if (this.status === "failed" || this.status === "conflict") return
    this.setStatus("saving")
    this.schedule()
  }

  // Call on leave/visibility hidden as a best effort; browser exit can interrupt
  // the request. Only a matching successful response produces "saved".
  async flush(): Promise<void> {
    clearTimeout(this.timer)
    if (this.status === "conflict" || this.status === "failed") return
    if (this.flight) { this.flushAfterFlight = true; return this.flight }
    if (!this.pending && !this.dirty()) { this.setStatus("saved"); return }
    this.pending ??= { request_id: crypto.randomUUID(), expected_version: this.version, progress: structuredClone(this.desired) }
    const request = this.pending
    this.setStatus("saving")
    this.flight = (async () => {
      try {
        const receipt = await Promise.resolve().then(() => this.save(structuredClone(request)))
        if (receipt.request_id !== request.request_id || !receipt.version) throw new Error("unconfirmed draft receipt")
        this.version = receipt.version
        this.saved = structuredClone(request.progress)
        this.pending = null
        this.setStatus(this.dirty() ? "saving" : "saved")
      } catch (error) {
        this.setStatus((error as { response?: { status?: number } })?.response?.status === 409 ? "conflict" : "failed")
      } finally {
        this.flight = null
        if (this.status === "saving") {
          if (this.flushAfterFlight) this.due = 0
          this.schedule()
        }
        this.flushAfterFlight = false
      }
    })()
    return this.flight
  }

  async retry(): Promise<void> {
    if (this.status !== "failed") return
    this.setStatus("saving")
    await this.flush()
  }
}
