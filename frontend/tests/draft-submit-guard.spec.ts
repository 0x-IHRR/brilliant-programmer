import { expect, test } from "@playwright/test"

test("选择与删除回包未确认时不能交旧答案，确认后交所选整份版本", async ({ page }) => {
  test.skip(!process.env.DRAFT_BROWSER_TOKEN, "受控真实案例")
  const token = process.env.DRAFT_BROWSER_TOKEN!, id = process.env.DRAFT_FIRST_RUN!
  const headers = { Authorization: `Bearer ${token}` }, path = `/api/v1/training/tasks/${id}/draft`
  const run = await (await page.request.get(`/api/v1/training/tasks/${id}`, { headers })).json()
  const progress = (reason: string) => ({ step: "judgments", based_on_submission_id: null, answers: run.case.judgments.map((j: { id: string; kind: string; options: string[] }) => ({ judgment_id: j.id, value: j.kind === "order" ? j.options.map((_, i) => i) : j.kind === "prediction" ? "需核对" : 0, reason })) })
  let collection = await (await page.request.get(path + "/versions", { headers })).json()
  for (const reason of ["选择的新版本 B", "当前旧版本 A"]) {
    expect((await page.request.put(path, { headers, data: { request_id: crypto.randomUUID(), expected_version: collection.current, observed_revision: collection.revision, generation: collection.generation, progress: progress(reason) } })).status()).toBe(200)
    collection = await (await page.request.get(path + "/versions", { headers })).json()
  }
  await page.addInitScript(value => sessionStorage.setItem("token", value), token)
  await page.goto(`/?training_run=${id}`)
  const reason = page.getByLabel("这一判断的理由", { exact: true }).first()
  await expect(reason).toHaveValue("当前旧版本 A")
  await page.getByRole("checkbox", { name: /允许将当前公开题面/ }).check()
  const submit = page.getByRole("button", { name: "正式交卷", exact: true })
  const form = page.locator("form").filter({ has: submit })
  let posts = 0
  page.on("request", request => { if (request.method() === "POST" && request.url().endsWith(`/tasks/${id}/submissions`)) posts++ })
  async function holdResponse(pattern: string, method: string) {
    let release!: () => void, committed!: () => void
    const gate = new Promise<void>(resolve => { release = resolve }), reached = new Promise<void>(resolve => { committed = resolve })
    await page.route(pattern, async route => {
      if (route.request().method() !== method) { await route.continue(); return }
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      committed()
      await gate
      await route.fulfill({ response })
    })
    return { release, reached }
  }
  if (!await page.getByText("草稿版本与删除", { exact: true }).evaluate(el => (el.parentElement as HTMLDetailsElement).open)) await page.getByText("草稿版本与删除", { exact: true }).click()
  const deletion = await holdResponse(`**/tasks/${id}/draft`, "DELETE")
  page.once("dialog", dialog => dialog.accept())
  await page.getByRole("button", { name: "删除指定当前草稿" }).click()
  await deletion.reached
  await expect(submit).toBeDisabled()
  await form.dispatchEvent("submit")
  expect(posts).toBe(0)
  deletion.release()
  await expect(page.getByText(/指定当前草稿已删除；/)).toBeVisible()
  await page.unroute(`**/tasks/${id}/draft`)
  collection = await (await page.request.get(path + "/versions", { headers })).json()
  expect((await page.request.put(path, { headers, data: { request_id: crypto.randomUUID(), expected_version: null, observed_revision: collection.revision, generation: collection.generation, progress: progress("当前旧版本 A") } })).status()).toBe(200)
  collection = await (await page.request.get(path + "/versions", { headers })).json()
  expect((await page.request.post(path + "/choose", { headers, data: { observed_revision: collection.revision, version: collection.current } })).status()).toBe(200)
  await page.reload()
  await expect(reason).toHaveValue("当前旧版本 A")
  await page.getByRole("checkbox", { name: /允许将当前公开题面/ }).check()
  if (!await page.getByText("草稿版本与删除", { exact: true }).evaluate(el => (el.parentElement as HTMLDetailsElement).open)) await page.getByText("草稿版本与删除", { exact: true }).click()
  await page.getByRole("article", { name: /^草稿版本 / }).filter({ hasText: "当前旧版本 A" }).last().getByRole("button", { name: /选择版本/ }).click()
  await expect(submit).toBeEnabled()
  if (!await page.getByText("草稿版本与删除", { exact: true }).evaluate(el => (el.parentElement as HTMLDetailsElement).open)) await page.getByText("草稿版本与删除", { exact: true }).click()
  const choose = await holdResponse(`**/tasks/${id}/draft/choose`, "POST")
  await page.getByRole("article", { name: "草稿版本 1", exact: true }).getByRole("button", { name: "选择版本 1" }).click()
  await choose.reached
  await expect(submit).toBeDisabled()
  await form.dispatchEvent("submit")
  expect(posts).toBe(0)
  await expect(reason).toHaveValue("当前旧版本 A")
  choose.release()
  await expect(reason).toHaveValue("选择的新版本 B")
  await page.unroute(`**/tasks/${id}/draft/choose`)
  await submit.click()
  await expect.poll(async () => (await (await page.request.get(`/api/v1/training/tasks/${id}/submissions`, { headers })).json()).submissions.length).toBe(1)
  expect(posts).toBe(1)
})
