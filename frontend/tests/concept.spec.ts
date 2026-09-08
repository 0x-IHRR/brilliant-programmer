import { expect, test } from "@playwright/test"

test("未作答求助、主动深入与内容绑定渲染事实在320px和200%可用", async ({
  page,
}) => {
  test.skip(
    !process.env.CONCEPT_BROWSER_TOKEN,
    "由 concept_browser.py 提供真实任务",
  )
  await page.setViewportSize({ width: 320, height: 760 })
  page.on("pageerror", (error) =>
    console.error("Concept page error:", error.message),
  )
  await page.goto("/")
  await page.evaluate(
    (token) => sessionStorage.setItem("token", token!),
    process.env.CONCEPT_BROWSER_TOKEN,
  )
  await page.reload()
  const training = page.getByRole("region", { name: "随机第一关" })
  await expect(
    training.getByText("比较请求证据", { exact: true }),
  ).toBeVisible()
  await training.getByRole("button", { name: "概念", exact: true }).click()
  const coach = page.getByRole("region", { name: "概念教练" })
  await coach.getByRole("textbox").fill("幂等是什么意思？")
  await coach.getByRole("checkbox").check()
  await coach.getByRole("button", { name: "白话解释", exact: true }).focus()
  await page.keyboard.press("Enter")
  await expect(
    coach.getByRole("button", { name: "查看说明", exact: true }),
  ).toBeVisible({ timeout: 15000 })
  await expect(coach.getByText("白话：", { exact: false })).toHaveCount(0)
  await expect(coach).not.toContainText("HIDDEN_")
  await coach.getByRole("button", { name: "查看说明", exact: true }).click()
  await expect(coach.getByText(/^白话：/)).toBeVisible()
  await expect(coach.getByText(/^小例子：/)).toBeVisible()
  await expect(coach.getByText(/^对应材料：/)).toBeVisible()
  await expect(coach.getByText(/^进一步原理：/)).toHaveCount(0)
  await expect(
    coach.getByRole("button", { name: "展开更深原理" }),
  ).toBeVisible()
  await coach.screenshot({ path: "test-results/concept-basic-320.png" })
  await coach.getByRole("button", { name: "展开更深原理" }).click()
  await expect(
    coach.getByRole("button", { name: "查看说明", exact: true }),
  ).toHaveCount(2, { timeout: 15000 })
  await coach
    .getByRole("button", { name: "查看说明", exact: true })
    .last()
    .click()
  await expect(coach.getByText(/^进一步原理：/)).toBeVisible()
  await coach.getByText("交付事实与历史说明", { exact: true }).last().click()
  await expect(coach.getByText(/页面完整渲染回执已保存/).last()).toBeVisible()
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%"
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  await coach.getByText(/^进一步原理：/).scrollIntoViewIfNeeded()
  await page.screenshot({ path: "test-results/concept-deep-200.png" })
  await page.reload()
  await training.getByRole("button", { name: "概念", exact: true }).click()
  await coach.getByText("交付事实与历史说明", { exact: true }).first().click()
  await expect(coach.getByText(/页面完整渲染回执已保存/).first()).toBeVisible()
  // Lose the publication response after the server commits: no invented partial/receipt.
  await page.route("**/help/*/deliver", async (route) => {
    await route.fetch()
    await route.abort()
  })
  await coach
    .getByRole("button", { name: "查看说明", exact: true })
    .first()
    .click()
  await expect(coach.getByRole("alert")).toBeVisible()
  await coach.getByRole("button", { name: "重新读取帮助" }).click()
  await expect(coach.getByText(/交付待核对/)).toHaveCount(3)
  await expect(coach.getByText(/页面完整渲染回执已保存/)).toHaveCount(2)
  await expect(coach.getByText(/^白话：/)).toHaveCount(0)
})

test("卸载与会话更换取消待渲染回执，保留原未知尝试", async ({ page }) => {
  test.skip(
    !process.env.CONCEPT_BROWSER_TOKEN,
    "由 concept_browser.py 提供真实任务",
  )
  page.on("pageerror", (error) =>
    console.error("Concept page error:", error.message),
  )
  await page.goto("/")
  await page.evaluate(
    (token) => sessionStorage.setItem("token", token!),
    process.env.CONCEPT_BROWSER_TOKEN,
  )
  await page.reload()
  const coach = page.getByRole("region", { name: "概念教练" })
  await expect(
    coach.getByRole("button", { name: "查看说明" }).first(),
  ).toBeVisible()
  let receipts = 0
  page.on("request", (request) => {
    if (request.url().endsWith("/receipt")) receipts++
  })
  await page.evaluate(() => {
    const originalFrame = window.requestAnimationFrame.bind(window)
    const frames = new Map<number, FrameRequestCallback>()
    let id = 0
    window.requestAnimationFrame = (callback) => {
      frames.set(++id, callback)
      return id
    }
    window.cancelAnimationFrame = (key) => {
      frames.delete(key)
    }
    Object.assign(window, {
      conceptPending: () => frames.size,
      conceptRestoreScheduler: () => {
        window.requestAnimationFrame = originalFrame
      },
      conceptFlush: () => {
        for (let i = 0; i < 2; i++) {
          const pending = [...frames.values()]
          frames.clear()
          pending.forEach((callback) => callback(performance.now()))
        }
      },
    })
  })
  const pendingFrames = () =>
    page.evaluate(() =>
      (window as unknown as { conceptPending: () => number }).conceptPending(),
    )
  // Hold the post-publication history read: visible prose is not action completion.
  let releaseHistory!: () => void
  const historyGate = new Promise<void>((resolve) => {
    releaseHistory = resolve
  })
  await page.route("**/help", async (route) => {
    if (route.request().method() === "GET") await historyGate
    await route.continue()
  })
  // Dispatch without Playwright actionability's own RAF dependency.
  await coach
    .getByRole("button", { name: "查看说明" })
    .first()
    .dispatchEvent("click")
  await expect(coach.getByText(/^白话：/)).toBeVisible()
  await expect(
    coach.getByRole("button", { name: "查看说明" }).first(),
  ).toBeDisabled()
  releaseHistory()
  await expect(
    coach.getByRole("button", { name: "查看说明" }).first(),
  ).toBeEnabled()
  await page.unroute("**/help")
  await expect.poll(pendingFrames).toBeGreaterThan(0)
  await page.evaluate(() => {
    sessionStorage.setItem("token", "synthetic-changed-session")
    ;(window as unknown as { conceptFlush: () => void }).conceptFlush()
  })
  expect(receipts).toBe(0)
  await page.evaluate(
    (token) => sessionStorage.setItem("token", token!),
    process.env.CONCEPT_BROWSER_TOKEN,
  )
  await expect(
    coach.getByRole("button", { name: "查看说明" }).first(),
  ).toBeEnabled()
  const secondPublication = page.waitForResponse(
    (response) =>
      response.url().endsWith("/deliver") &&
      response.request().method() === "POST",
  )
  await coach
    .getByRole("button", { name: "查看说明" })
    .first()
    .dispatchEvent("click")
  expect((await secondPublication).ok()).toBe(true)
  await expect(
    coach.getByRole("button", { name: "查看说明" }).first(),
  ).toBeEnabled()
  await expect.poll(pendingFrames).toBeGreaterThan(0)
  await page.evaluate(() => {
    ;(
      window as unknown as { conceptRestoreScheduler: () => void }
    ).conceptRestoreScheduler()
  })
  await page
    .getByRole("button", { name: "退出登录", exact: true })
    .dispatchEvent("click")
  await expect(coach).toHaveCount(0)
  await page.evaluate(() => {
    ;(window as unknown as { conceptFlush: () => void }).conceptFlush()
  })
  expect(receipts).toBe(0)
})
