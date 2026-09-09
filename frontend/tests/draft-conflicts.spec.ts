import { expect, test } from "@playwright/test"

test("三台设备保留版本、明确选择、删除和旧设备防复活", async ({ browser, page }) => {
  test.skip(!process.env.DRAFT_BROWSER_TOKEN, "受控真实案例")
  const id = process.env.DRAFT_FIRST_RUN!
  const token = process.env.DRAFT_BROWSER_TOKEN!
  const headers = { Authorization: `Bearer ${token}` }
  const path = `/api/v1/training/tasks/${id}/draft`
  const contexts = [page.context(), await browser.newContext(), await browser.newContext()]
  const pages = [page, await contexts[1].newPage(), await contexts[2].newPage()]
  const texts = ["第一设备依据", "第二设备依据", "第三设备依据"]
  try {
    for (const p of pages) {
      await p.addInitScript(value => sessionStorage.setItem("token", value), token)
      await p.goto(`/?training_run=${id}`)
      await expect(p.getByText("尚无已保存草稿", { exact: true })).toBeVisible()
    }
    for (let i = 0; i < pages.length; i++) {
      await pages[i].getByLabel("这一判断的理由", { exact: true }).first().fill(texts[i])
      await expect(pages[i].getByText(i === 0 ? "草稿已保存" : "草稿版本冲突，当前输入保留，未覆盖其他版本", { exact: true })).toBeVisible()
    }
    const b = pages[1]
    await b.getByRole("button", { name: "读取草稿并比较" }).click()
    for (const text of texts) await expect(b.getByRole("article", { name: /^草稿版本 / }).filter({ hasText: text })).toHaveCount(1)
    const state = await (await b.request.get(path + "/versions", { headers })).json()
    expect(state.unresolved).toHaveLength(3)
    const run = await (await b.request.get(`/api/v1/training/tasks/${id}`, { headers })).json()
    const denied = await b.request.post(`/api/v1/training/tasks/${id}/submissions`, { headers, data: { request_id: crypto.randomUUID(), expected_config_version: run.config_version, disclosure_accepted: true, answers: run.case.judgments.map((j: { id: string; kind: string; options: string[] }) => ({ judgment_id: j.id, value: j.kind === "order" ? j.options.map((_, i) => i) : j.kind === "prediction" ? "需核对" : 0, reason: "需要核对材料" })) } })
    expect(denied.status()).toBe(409)
    await b.getByRole("article", { name: /^草稿版本 / }).filter({ hasText: texts[1] }).getByRole("button", { name: /选择版本/ }).click()
    await expect(b.getByText("草稿已保存", { exact: true })).toBeVisible()
    await expect(b.getByLabel("这一判断的理由", { exact: true }).first()).toHaveValue(texts[1])
    await b.reload()
    await expect(b.getByLabel("这一判断的理由", { exact: true }).first()).toHaveValue(texts[1])
    await b.getByText("草稿版本与删除", { exact: true }).click()
    expect((await (await b.request.get(path + "/versions", { headers })).json()).versions).toHaveLength(3)
    await b.setViewportSize({ width: 320, height: 760 })
    await b.getByRole("article", { name: /^草稿版本 / }).filter({ hasText: texts[1] }).scrollIntoViewIfNeeded()
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await b.screenshot({ path: "test-results/conflicts-320.png" })
    await b.evaluate(() => { document.documentElement.style.fontSize = "200%" })
    await b.getByRole("button", { name: "删除指定当前草稿" }).scrollIntoViewIfNeeded()
    expect(await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await b.screenshot({ path: "test-results/conflicts-200.png" })
    b.once("dialog", dialog => dialog.accept())
    await b.getByRole("button", { name: "删除指定当前草稿" }).click()
    await expect(b.getByText(/指定当前草稿已删除；/)).toBeVisible()
    const deleted = await (await b.request.get(path + "/versions", { headers })).json()
    expect(deleted.current).toBeNull()
    expect(deleted.versions).toHaveLength(2)
    await pages[0].getByLabel("这一判断的理由", { exact: true }).first().fill("删除后旧设备未保存输入")
    await expect(pages[0].getByText("草稿版本冲突，当前输入保留，未覆盖其他版本", { exact: true })).toBeVisible()
    expect((await (await b.request.get(path + "/versions", { headers })).json())).toEqual(deleted)
    await b.reload()
    await b.getByRole("button", { name: "判断", exact: true }).click()
    await expect(b.getByLabel("这一判断的理由", { exact: true }).first()).toHaveValue("")
    const records = await (await b.request.get(`/api/v1/training/tasks/${id}/submissions`, { headers })).json()
    expect(records.submissions).toHaveLength(0)
    expect(records.awarded_points).toBe(0)
  } finally { await contexts[1].close(); await contexts[2].close() }
})

test("迟到选择与删除失败保留本机编辑并可明确恢复", async ({ page }) => {
  test.skip(!process.env.DRAFT_BROWSER_TOKEN, "受控真实案例")
  const id = process.env.DRAFT_SECOND_RUN!, token = process.env.DRAFT_BROWSER_TOKEN!
  const headers = { Authorization: `Bearer ${token}` }, path = `/api/v1/training/tasks/${id}/draft`
  await page.addInitScript(value => sessionStorage.setItem("token", value), token)
  await page.goto(`/?training_run=${id}`)
  const reason = page.getByLabel("这一判断的理由", { exact: true }).first()
  await reason.fill("删除失败前输入")
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await page.getByText("草稿版本与删除", { exact: true }).click()
  // Failure before commit: no deletion is asserted, new typing remains in editor.
  await page.route(`**/tasks/${id}/draft`, route => route.request().method() === "DELETE" ? route.fulfill({ status: 503, json: { detail: "controlled failure" } }) : route.continue())
  page.once("dialog", d => d.accept())
  await page.getByRole("button", { name: "删除指定当前草稿" }).click()
  await expect(page.getByText(/删除未确认成功或当前版本已变化/)).toBeVisible()
  await expect(reason).toHaveValue("删除失败前输入")
  await page.unroute(`**/tasks/${id}/draft`)
  await reason.fill("删除失败后继续输入")
  await page.getByRole("button", { name: "读取草稿并比较" }).click()
  await page.getByRole("button", { name: "保留本机输入，按已读版本继续保存" }).click()
  const row = page.getByRole("article", { name: /^草稿版本 / }).filter({ hasText: "删除失败后继续输入" }).last()
  await row.getByRole("button", { name: /选择版本/ }).click()
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  expect((await (await page.request.get(path, { headers })).json()).progress.answers[0].reason).toBe("删除失败后继续输入")
  let release!: () => void, entered!: () => void
  const held = new Promise<void>(resolve => { release = resolve }), waiting = new Promise<void>(resolve => { entered = resolve })
  await page.route(`**/tasks/${id}/draft/choose`, async route => { entered(); await held; await route.continue() })
  const seen = await (await page.request.get(path + "/versions", { headers })).json()
  await page.getByText("草稿版本与删除", { exact: true }).click()
  await row.getByRole("button", { name: /选择版本/ }).click()
  await waiting
  const current = seen.versions.find((v: { version: string }) => v.version === seen.current)
  const raced = await page.request.put(path, { headers, data: { request_id: crypto.randomUUID(), expected_version: seen.current, observed_revision: seen.revision, generation: seen.generation, progress: { ...current.progress, step: "coach" } } })
  expect(raced.status()).toBe(200)
  release()
  await expect(page.getByText(/选择未确认成功或版本集合已变化/)).toBeVisible()
  await expect(reason).toHaveValue("删除失败后继续输入")
  expect((await (await page.request.get(path, { headers })).json()).progress.step).toBe("coach")
  await page.unroute(`**/tasks/${id}/draft/choose`)
})
