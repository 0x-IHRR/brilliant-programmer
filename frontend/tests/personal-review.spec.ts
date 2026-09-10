import { expect, test } from "@playwright/test"

test("本人复盘与真实 JSON 下载一致，失败可重试且 320px/200% 可用", async ({
  page,
}) => {
  test.skip(
    !process.env.TRAINING_BROWSER_TOKEN,
    "由 training_browser.py 提供真实合成学习记录",
  )
  const token = process.env.TRAINING_BROWSER_TOKEN!
  const headers = { Authorization: `Bearer ${token}` }
  await page.setViewportSize({ width: 320, height: 780 })
  await page.goto("/")
  await page.evaluate((value) => sessionStorage.setItem("token", value), token)
  await page.reload()

  const region = page.getByRole("region", { name: "个人复盘与导出" })
  const server = await (
    await page.request.get("/api/v1/personal-review/export", { headers })
  ).json()
  expect(server.rounds.length).toBeGreaterThan(0)
  await region.getByRole("button", { name: "读取本人复盘" }).focus()
  await page.keyboard.press("Enter")
  await expect(region.getByRole("status")).toContainText(
    `${server.rounds.length} 轮`,
  )
  await expect(region.locator("[data-run-id]")).toHaveCount(
    server.rounds.length,
  )
  await region
    .locator("[data-run-id]")
    .first()
    .locator(":scope > summary")
    .click()
  await expect(
    region.getByText("原始作答与后续补答", { exact: true }).first(),
  ).toBeVisible()
  expect(JSON.stringify(server.rounds[0].task)).not.toContain("HIDDEN_REASON")

  let failed = false
  await page.route("**/api/v1/personal-review/export", async (route) => {
    if (failed) return route.continue()
    failed = true
    await route.abort("connectionreset")
  })
  await region.getByRole("button", { name: "读取并下载 JSON" }).click()
  await expect(region.getByRole("alert")).toContainText("本次读取或导出失败")
  await page.unroute("**/api/v1/personal-review/export")

  const download = page.waitForEvent("download")
  await region.getByRole("button", { name: "读取并下载 JSON" }).focus()
  await page.keyboard.press("Enter")
  const saved = await download
  expect(saved.suggestedFilename()).toBe("personal-learning.json")
  const stream = await saved.createReadStream()
  let text = ""
  for await (const chunk of stream) text += chunk.toString()
  const exported = JSON.parse(text)
  expect(exported.user_id).toBe(server.user_id)
  expect(
    exported.rounds.map((item: { task: { id: string } }) => item.task.id),
  ).toEqual(server.rounds.map((item: { task: { id: string } }) => item.task.id))
  expect(exported.rounds[0].evaluation).toEqual(server.rounds[0].evaluation)
  expect(exported.rounds[0].submissions).toEqual(server.rounds[0].submissions)
  expect(text).not.toContain("receipt_token")
  expect(text).not.toContain("api_key")

  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%"
  })
  await region
    .getByRole("button", { name: "读取并下载 JSON" })
    .scrollIntoViewIfNeeded()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await region.screenshot({ path: "test-results/personal-review-200.png" })
})
