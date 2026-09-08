import { expect, test } from "bun:test"
import { DraftAutosave, type DraftProgress, type DraftWrite, type SaveStatus } from "../src/features/draftAutosave"

const progress = (reason = ""): DraftProgress => ({ answers: [{ judgment_id: "choice", value: null, reason }], step: "judgments", based_on_submission_id: null })
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(yes => { resolve = yes })
  return { promise, resolve }
}

test("one second after last edit; response required for saved", async () => {
  const writes: DraftWrite[] = [], states: SaveStatus[] = []
  const gate = deferred<{ version: string; request_id: string }>()
  const saver = new DraftAutosave(progress(), null, async request => { writes.push(request); return gate.promise }, state => states.push(state))
  saver.edit(progress("first"))
  await pause(550)
  saver.edit(progress("last"))
  await pause(550)
  expect(writes).toHaveLength(0)
  await pause(500)
  expect(writes).toHaveLength(1)
  expect(writes[0].progress.answers[0].reason).toBe("last")
  expect(saver.status).toBe("saving")
  gate.resolve({ version: "saved-" + writes[0].request_id, request_id: writes[0].request_id })
  await saver.flush()
  expect(saver.status).toBe("saved")
  expect(states).toContain("saved")
})

test("leave flushes now; in-flight edits wait and keep the next version", async () => {
  const writes: DraftWrite[] = []
  const gate = deferred<{ version: string; request_id: string }>()
  const saver = new DraftAutosave(progress(), null, async request => {
    writes.push(request)
    return writes.length === 1 ? gate.promise : { version: "saved-" + request.request_id, request_id: request.request_id }
  }, () => {})
  saver.edit(progress("first"))
  const first = saver.flush()
  await pause(0)
  saver.edit(progress("second"))
  void saver.flush()
  expect(writes).toHaveLength(1)
  gate.resolve({ version: "saved-" + writes[0].request_id, request_id: writes[0].request_id })
  await first
  await pause(20)
  expect(writes).toHaveLength(2)
  expect(writes[1].expected_version).toBe("saved-" + writes[0].request_id)
  expect(writes[1].progress.answers[0].reason).toBe("second")
  expect(saver.status).toBe("saved")
})

test("lost response retains request identity and newer input through retry", async () => {
  const writes: DraftWrite[] = []
  const saver = new DraftAutosave(progress(), null, async request => {
    writes.push(request)
    if (writes.length === 1) throw new Error("offline")
    return { version: "saved-" + request.request_id, request_id: request.request_id }
  }, () => {})
  saver.edit(progress("first"))
  await saver.flush()
  expect(saver.status).toBe("failed")
  saver.edit(progress("newer while offline"))
  await saver.retry()
  expect(writes[1]).toEqual(writes[0])
  expect(saver.status).toBe("saving")
  expect(saver.progress.answers[0].reason).toBe("newer while offline")
  await saver.flush()
  expect(writes[2].expected_version).toBe("saved-" + writes[0].request_id)
  expect(saver.status).toBe("saved")
})

test("409 keeps local input, blocks auto-overwrite and does not relabel saved", async () => {
  let calls = 0
  const saver = new DraftAutosave(progress(), "existing-version", async () => { calls++; throw { response: { status: 409 } } }, () => {})
  saver.edit(progress("device two"))
  await saver.flush()
  expect(saver.status).toBe("conflict")
  saver.edit(progress("still editable"))
  await saver.retry()
  await saver.flush()
  expect(calls).toBe(1)
  expect(saver.progress.answers[0].reason).toBe("still editable")
})

test("wrong receipt and synchronous transport failure are retryable, never saved", async () => {
  let calls = 0
  const saver = new DraftAutosave(progress(), null, request => {
    calls++
    if (calls === 1) throw new Error("request setup failed")
    return Promise.resolve({ version: "saved-" + request.request_id, request_id: calls === 2 ? "wrong" : request.request_id })
  }, () => {})
  saver.edit(progress("retained"))
  await saver.flush()
  expect(saver.status).toBe("failed")
  await saver.retry()
  expect(saver.status).toBe("failed")
  await saver.retry()
  expect(saver.status).toBe("saved")
})

test("a newer edit restarts debounce after an older timer expired during flight", async () => {
  const writes: DraftWrite[] = []
  const times: number[] = []
  const gate = deferred<{ version: string; request_id: string }>()
  const saver = new DraftAutosave(progress(), null, async request => {
    writes.push(request)
    times.push(Date.now())
    return writes.length === 1 ? gate.promise : { version: "saved-" + request.request_id, request_id: request.request_id }
  }, () => {})
  saver.edit(progress("first"))
  const first = saver.flush()
  await pause(0)
  saver.edit(progress("second"))
  await pause(1100) // This timer expires while the first write is still in flight.
  expect(writes).toHaveLength(1)
  const lastEdit = Date.now()
  saver.edit(progress("third"))
  gate.resolve({ version: "saved-" + writes[0].request_id, request_id: writes[0].request_id })
  await first
  await pause(50)
  expect(writes).toHaveLength(1)
  expect(saver.status).toBe("saving")
  await pause(1000)
  expect(writes).toHaveLength(2)
  expect(times[1] - lastEdit).toBeGreaterThanOrEqual(1000)
  expect(writes[1].progress.answers[0].reason).toBe("third")
  expect(writes[1].expected_version).toBe("saved-" + writes[0].request_id)
  expect(saver.status).toBe("saved")
})
