import { expect, test, type Page } from "@playwright/test"

async function enter(page: Page) {
  await page.goto("/")
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.DRAFT_BROWSER_TOKEN)
  await page.reload()
  await expect(page.getByText("尚无已保存草稿", { exact: true }).or(page.getByText("草稿已保存", { exact: true }))).toBeVisible()
}

test("草稿真实断网重连、失响应、刷新、离开和另一设备冲突", async ({ page, browser }) => {
  test.skip(!process.env.DRAFT_BROWSER_TOKEN, "由 draft_browser.py 提供真实任务")
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.setViewportSize({ width: 320, height: 760 })
  await enter(page)
  const training = page.getByRole("region", { name: "随机第一关" })
  await training.getByRole("button", { name: "判断", exact: true }).click()
  const reason = page.getByLabel("这一判断的理由", { exact: true }).first()
  await reason.fill("还没有判断完，先保存这一步")
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await expect(reason).toHaveValue("还没有判断完，先保存这一步")
  await page.context().setOffline(true)
  await reason.fill("离线时保留的新输入")
  await expect(page.getByText("草稿保存失败，当前输入保留", { exact: true })).toBeVisible()
  await expect(reason).toHaveValue("离线时保留的新输入")
  await page.context().setOffline(false)
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await page.reload()
  await expect(reason).toHaveValue("离线时保留的新输入")
  // Server commits, but the response is lost. Retry reconciles the same request.
  await page.route("**/draft", async route => {
    if (route.request().method() !== "PUT") return route.continue()
    await route.fetch(); await route.abort()
  })
  await reason.fill("保存确认丢失仍保留")
  await expect(page.getByText("草稿保存失败，当前输入保留", { exact: true })).toBeVisible()
  await page.unroute("**/draft")
  await reason.fill("确认丢失后继续写的新输入")
  await page.getByRole("button", { name: "重试保存草稿" }).click()
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await page.reload()
  await expect(reason).toHaveValue("确认丢失后继续写的新输入")
  // Independent context reads the same saved run, not this page's input state.
  const device = await browser.newContext({ viewport: { width: 320, height: 760 } })
  const other = await device.newPage()
  await enter(other)
  const otherReason = other.getByLabel("这一判断的理由", { exact: true }).first()
  await expect(otherReason).toHaveValue("确认丢失后继续写的新输入")
  await reason.fill("第一台设备的新版本")
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await otherReason.fill("第二台设备未覆盖的输入")
  await expect(other.getByText("草稿版本冲突，当前输入保留，未覆盖其他版本", { exact: true })).toBeVisible()
  await expect(otherReason).toHaveValue("第二台设备未覆盖的输入")
  await other.getByRole("button", { name: "读取草稿并比较" }).click()
  await expect(other.getByText("第一台设备的新版本", { exact: false }).first()).toBeVisible()
  await other.getByRole("button", { name: "保留本机输入，按已读版本继续保存" }).click()
  await other.getByRole("article", { name: /^草稿版本 / }).filter({ hasText: "第二台设备未覆盖的输入" }).last().getByRole("button", { name: /选择版本/ }).click()
  await expect(other.getByText("草稿已保存", { exact: true })).toBeVisible()
  await device.close()
  await page.reload()
  await expect(reason).toHaveValue("第二台设备未覆盖的输入")
  await reason.fill("切换旧轮时马上保存")
  await page.getByLabel("查看已有任务").selectOption(process.env.DRAFT_FIRST_RUN!)
  await expect(page.getByText("尚无已保存草稿", { exact: true })).toBeVisible()
  await page.getByLabel("查看已有任务").selectOption(process.env.DRAFT_SECOND_RUN!)
  await expect(reason).toHaveValue("切换旧轮时马上保存")
  await reason.scrollIntoViewIfNeeded()
  await page.screenshot({ path: "test-results/draft-320.png" })
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
  await page.getByText("草稿已保存", { exact: true }).scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/draft-200.png" })
  expect(errors).toEqual([])
})

test("旧轮链接恢复按稳定判断ID对齐的未完成草稿", async ({ page }) => {
  test.skip(!process.env.DRAFT_BROWSER_TOKEN, "由 draft_browser.py 提供真实任务")
  const runId = process.env.DRAFT_FIRST_RUN!
  const endpoint = `/api/v1/training/tasks/${runId}/draft`
  const headers = { Authorization: `Bearer ${process.env.DRAFT_BROWSER_TOKEN}` }
  const previous = await (await page.request.get(endpoint, { headers })).json()
  const collection = await (await page.request.get(endpoint + "/versions", { headers })).json()
  const written = await page.request.put(endpoint, { headers, data: {
    request_id: crypto.randomUUID(), expected_version: previous?.version ?? null, observed_revision: collection.revision, generation: collection.generation,
    progress: { answers: [
      { judgment_id: "j3", value: "还不确定", reason: "预测未完" },
      { judgment_id: "j2", value: [2], reason: "排序未完" },
      { judgment_id: "j1", value: 0, reason: "选择未完" },
    ], step: "judgments", based_on_submission_id: null },
  } })
  expect(written.status()).toBe(200)
  await page.setViewportSize({ width: 320, height: 760 })
  await page.goto(`/?training_run=${runId}`)
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.DRAFT_BROWSER_TOKEN)
  await page.reload()
  const reasons = page.getByLabel("这一判断的理由", { exact: true })
  await expect(reasons.nth(0)).toHaveValue("选择未完")
  await expect(reasons.nth(1)).toHaveValue("排序未完")
  await expect(reasons.nth(2)).toHaveValue("预测未完")
  const order = page.getByRole("region", { name: "必答判断" }).getByRole("combobox")
  await expect(order.nth(0)).toHaveValue("2")
  await expect(order.nth(1)).toHaveValue("")
  await expect(page.getByLabel("你的预测", { exact: true })).toHaveValue("还不确定")
  await reasons.nth(0).focus()
  await page.keyboard.press("End")
  await page.keyboard.type("，键盘继续")
  await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByLabel("查看已有任务")).toHaveValue(runId)
  await expect(reasons.nth(0)).toHaveValue("选择未完，键盘继续")
})

test("旧链接跨账号、无效ID和临时恢复失败保留当前可用任务", async ({ page }) => {
  test.skip(!process.env.DRAFT_BROWSER_TOKEN, "由 draft_browser.py 提供真实任务")
  const oldRun = process.env.DRAFT_FIRST_RUN!
  await page.goto(`/?training_run=${oldRun}`)
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.DRAFT_SWITCH_TOKEN)
  await page.reload()
  await expect(page.getByText("比较请求证据", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "退出登录", exact: true }).click()
  await expect(page.getByText("已退出当前设备", { exact: true })).toBeVisible()
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.DRAFT_OTHER_TOKEN)
  await page.reload()
  const training = page.getByRole("region", { name: "随机第一关" })
  await expect(training.getByRole("button", { name: "帮我选一关", exact: true })).toBeVisible()
  await expect(training.getByRole("alert")).toContainText("原轮链接不可用")
  expect(new URL(page.url()).searchParams.has("training_run")).toBe(false)
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.DRAFT_BROWSER_TOKEN)
  for (const id of ["invalid-id", crypto.randomUUID()]) {
    await page.goto(`/?training_run=${id}`)
    await expect(training.getByText("比较请求证据", { exact: true })).toBeVisible()
    await expect(training.getByRole("alert")).toContainText("原轮链接不可用")
    expect(new URL(page.url()).searchParams.has("training_run")).toBe(false)
  }
  // Simulate an old run outside the recent-list window, using actual owned data.
  await page.route("**/api/v1/training/tasks", async route => {
    const response = await route.fetch()
    const data = await response.json()
    await route.fulfill({ response, json: data.filter((item: { id: string }) => item.id !== oldRun) })
  })
  await page.route(`**/api/v1/training/tasks/${oldRun}`, route => route.fulfill({ status: 503, json: { detail: "controlled temporary failure" } }))
  await page.goto(`/?training_run=${oldRun}`)
  await expect(training.getByText("比较请求证据", { exact: true })).toBeVisible()
  await expect(training.getByRole("alert")).toContainText("原轮暂时读取失败")
  expect(new URL(page.url()).searchParams.get("training_run")).toBe(oldRun)
  await page.unroute(`**/api/v1/training/tasks/${oldRun}`)
  await training.getByRole("button", { name: "重新读取任务与模型目的地" }).click()
  await expect(page.getByLabel("查看已有任务")).toHaveValue(oldRun)
  await expect(training.getByRole("alert")).toHaveCount(0)
})

for (const oldFails of [false, true]) {
  test(`同轮重复初始读取迟到${oldFails ? "失败" : "成功"}不覆盖新输入`, async ({ page }) => {
    test.skip(!process.env.DRAFT_BROWSER_TOKEN, "由 draft_browser.py 提供真实任务")
    const id = process.env.DRAFT_FIRST_RUN!
    let count = 0
    let release!: () => void
    const held = new Promise<void>(resolve => { release = resolve })
    await page.addInitScript(token => sessionStorage.setItem("token", token!), process.env.DRAFT_BROWSER_TOKEN)
    await page.route(`**/tasks/${id}/draft`, async route => {
      if (route.request().method() !== "GET" || ++count !== 1) return route.continue()
      const response = await route.fetch()
      await held
      if (oldFails) await route.fulfill({ status: 503, json: { detail: "controlled old failure" } })
      else await route.fulfill({ response })
    })
    await page.goto(`/?training_run=${id}`)
    await expect(page.getByRole("button", { name: "读取草稿并比较" })).toBeVisible()
    await page.getByRole("button", { name: "读取草稿并比较" }).click()
    const reason = page.getByLabel("这一判断的理由", { exact: true }).first()
    await expect(reason).toBeEnabled()
    // Desktop keeps the form visible without changing the saved panel.
    const input = `最新读取后输入，不许被旧响应覆盖：${oldFails}`
    await reason.fill(input)
    const responseDone = page.waitForResponse(response => response.url().endsWith(`/tasks/${id}/draft`) && response.request().method() === "GET")
    release()
    await responseDone
    await expect(page.getByText("草稿已保存", { exact: true })).toBeVisible()
    await expect(reason).toHaveValue(input)
    await expect(page.getByText(/草稿或提交记录读取失败/)).toHaveCount(0)
  })
}
