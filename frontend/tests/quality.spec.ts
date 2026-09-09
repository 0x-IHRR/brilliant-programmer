import { expect, test } from "@playwright/test"

const accounts = JSON.parse(process.env.QUALITY_BROWSER_ACCOUNTS ?? "{}") as Record<string, string>
const labels: Record<string, string> = {
  unverified: "评分可靠性未验证。连接成功和输出结构正确均不代表教学或判分合格。",
  failed: "已知评分未达标：仅可普通练习与复盘，服务端阻止新增独立证明和 Boss 晋升。",
  passed: "已有达标评测依据：仅适用于报告中的配置、评分规则与来源版本；实际题目仍逐次核对适用范围。",
  version_mismatch: "旧评测版本不匹配，当前评分可靠性未验证。",
}
for (const state of Object.keys(labels)) {
  test(`质量状态使用实际服务端报告：${state}`, async ({ page }) => {
    test.skip(!accounts[state], "由 quality_browser.py 提供合成报告，非真实质量证据")
    await page.addInitScript(token => sessionStorage.setItem("token", token), accounts[state])
    await page.goto("/")
    const quality = page.getByRole("region", { name: "评分质量", exact: true })
    await expect(quality.getByText(labels[state], { exact: true })).toBeVisible()
    if (state !== "unverified") {
      await quality.getByText("查看评测版本与依据", { exact: true }).click()
      await expect(quality.getByText(/样本 168/)).toBeVisible()
      await expect(quality.getByText(/报告 SHA-256/)).toBeVisible()
    }
    await page.reload()
    await expect(quality.getByText(labels[state], { exact: true })).toBeVisible()
  })
}

test("已知失败在服务端阻Boss，普通练习仍可；窄屏键盘可读", async ({ page }) => {
  test.skip(!accounts.failed, "需要合成报告测试账号")
  await page.setViewportSize({ width: 320, height: 780 })
  await page.addInitScript(token => sessionStorage.setItem("token", token), accounts.failed)
  await page.goto("/?boss=1")
  const quality = page.getByRole("region", { name: "评分质量", exact: true })
  await expect(quality.getByText(labels.failed, { exact: true })).toBeVisible()
  await quality.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/quality-320.png" })
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
  await quality.getByRole("heading").scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/quality-200.png" })
  await page.evaluate(() => { document.documentElement.style.fontSize = "" })
  const boss = page.getByRole("region", { name: "Boss挑战入口", exact: true })
  await boss.getByRole("checkbox").focus()
  await page.keyboard.press("Space")
  const denied = page.waitForResponse(r => r.url().endsWith("/api/v1/boss/start") && r.request().method() === "POST")
  await boss.getByRole("button", { name: "主动开始首阶段Boss（独立新案例）" }).click()
  expect((await denied).status()).toBe(409)
  await expect(boss.getByRole("alert")).toContainText("已有未达标评分依据")
  const training = page.getByRole("region", { name: "随机第一关", exact: true })
  await training.getByRole("checkbox").check()
  const created = page.waitForResponse(r => r.url().endsWith("/api/v1/training/random") && r.request().method() === "POST")
  await training.getByRole("button", { name: /帮我选一关|换个方向，主动开始新一关/ }).click()
  expect((await created).status()).toBe(202)
  await training.getByRole("button", { name: "停止本次生成", exact: true }).click()
  await expect(training.getByRole("status").filter({ hasText: "已停止" }).first()).toBeVisible()
})
