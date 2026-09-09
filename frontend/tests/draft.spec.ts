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
  const written = await page.request.put(endpoint, { headers, data: {
    request_id: crypto.randomUUID(), expected_version: previous?.version ?? null,
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
