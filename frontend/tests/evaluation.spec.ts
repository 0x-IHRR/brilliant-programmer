import { expect, test } from "@playwright/test"

test("评分中性补答、冻结与简短反馈在320px键盘和200%可用", async ({ page }) => {
  test.skip(!process.env.EVALUATION_BROWSER_TOKEN, "由受控 evaluation_browser.py 提供真实任务")
  page.on("pageerror", error => { console.error("Evaluation page error:", error.message) })
  await page.setViewportSize({ width: 320, height: 760 })
  await page.goto("/")
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.EVALUATION_BROWSER_TOKEN)
  await page.reload()
  const training = page.getByRole("region", { name: "随机第一关" })
  async function openJudgments() {
    await expect(training.getByLabel("草稿保存状态").getByRole("status")).not.toHaveText("正在读取已保存进度")
    await training.getByRole("button", { name: "判断", exact: true }).click()
  }
  let releaseDraft!: () => void
  const heldDraft = new Promise<void>(resolve => { releaseDraft = resolve })
  let sawDraft!: () => void
  const pendingDraft = new Promise<void>(resolve => { sawDraft = resolve })
  let holdFirst = true
  await page.route("**/training/tasks/*/draft", async route => {
    if (route.request().method() !== "PUT" || !holdFirst) { await route.continue(); return }
    holdFirst = false
    sawDraft()
    await heldDraft
    const response = await route.fetch()
    expect(response.status()).toBe(200)
    await route.fulfill({ response })
  })
  await expect(training.getByText("比较请求证据", { exact: true })).toBeVisible()
  await openJudgments()
  const feedback = page.getByRole("region", { name: "本次反馈" })
  await expect(feedback.getByText(/本评估接收方/)).toBeVisible()
  await expect(feedback.getByRole("button", { name: "提交一次中性补答并冻结" })).toBeVisible({ timeout: 15000 })
  await expect(feedback).not.toContainText("HIDDEN_")
  await feedback.screenshot({ path: "test-results/evaluation-clarification-320.png" })
  await pendingDraft
  await expect(training.getByLabel("草稿保存状态").getByRole("status")).toHaveText("草稿保存中")
  releaseDraft()
  // This flow expects a saved draft on reload, not a pagehide write racing restore.
  await expect(training.getByLabel("草稿保存状态").getByRole("status")).toHaveText("草稿已保存")
  await page.reload()
  await openJudgments()
  await feedback.getByRole("textbox", { name: "补充原答的意思和依据" }).fill("我指的是确认可能丢失，不能断言请求没有执行。")
  await feedback.getByRole("button", { name: "提交一次中性补答并冻结" }).focus()
  await page.keyboard.press("Enter")
  await expect(feedback.getByText("通过", { exact: true })).toBeVisible({ timeout: 15000 })
  await expect(feedback.getByText(/评估输入已冻结/)).toBeVisible()
  await expect(feedback.getByText(/^缺口：/)).toHaveCount(0)
  await expect(feedback.getByText("HIDDEN_HELP", { exact: false })).toHaveCount(0)
  await feedback.getByText("核对原答与冻结证据", { exact: true }).click()
  await expect(feedback.getByText(/原答：尚不能确认/)).toBeVisible()
  await expect(feedback.getByText(/许可补答：我指的是确认/)).toBeVisible()
  await feedback.screenshot({ path: "test-results/evaluation-result-320.png" })
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
  await feedback.getByRole("button", { name: "重新读取评分" }).scrollIntoViewIfNeeded()
  await expect(feedback.getByRole("button", { name: "重新读取评分" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await feedback.screenshot({ path: "test-results/evaluation-result-200.png" })
  await page.evaluate(() => { document.documentElement.style.fontSize = "" })
  await training.getByRole("button", { name: "编辑复盘补充" }).click()
  await training.getByRole("textbox", { name: "这一判断的理由", exact: true }).fill("冻结后的复盘补充，不应覆盖原答。")
  await training.getByText("保存本轮复盘补充，保留原答及冻结评分；不再次调用模型、评分或奖励。", { exact: true }).click()
  await expect(training.getByRole("button", { name: "保存复盘补充（不重评）" })).toBeEnabled()
  const submitted = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/submissions"))
  await training.getByRole("button", { name: "保存复盘补充（不重评）" }).focus()
  await page.keyboard.press("Enter")
  expect((await submitted).status()).toBe(202)
  await expect(training.getByText(/复盘补充已保存，原答和冻结评分不变/)).toBeVisible()
  await expect(feedback.getByText("通过", { exact: true })).toBeVisible()
  await expect(feedback.getByText(/原答：尚不能确认/)).toBeVisible()
})
