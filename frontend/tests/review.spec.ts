import { expect, test } from "@playwright/test"

test("一次复核失响应恢复、原评分保留、删除Key后历史可读，320px及200%", async ({ page }) => {
  test.skip(!process.env.REVIEW_BROWSER_TOKEN, "由 review_browser.py 提供真实账户与评分")
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  const identity = process.env.REVIEW_BROWSER_RUN!
  await page.setViewportSize({ width: 320, height: 800 })
  await page.goto(`/?training_run=${identity}`)
  await page.evaluate(token => sessionStorage.setItem("token", token!), process.env.REVIEW_BROWSER_TOKEN)
  await page.reload()
  const training = page.getByRole("region", { name: "随机第一关" })
  await expect(training.getByLabel("草稿保存状态").getByRole("status")).not.toHaveText("正在读取已保存进度")
  await training.getByRole("button", { name: "判断", exact: true }).click()
  const review = page.getByRole("region", { name: "评分复核" })
  await expect(review.getByRole("button", { name: "申请一次评分复核" })).toBeDisabled()
  await review.getByLabel("确认评分复核目的地").check()
  let submitted = 0
  await page.route(`**/training/tasks/${identity}/review`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return }
    submitted++
    const response = await route.fetch()
    expect(response.status()).toBe(202)
    // Server accepted exactly once, browser lost the acknowledgement.
    await route.abort("failed")
  })
  await review.getByRole("button", { name: "申请一次评分复核" }).focus()
  await page.keyboard.press("Enter")
  await expect(review.getByRole("alert")).toContainText("未确认操作结果")
  await page.reload()
  await expect(training.getByLabel("草稿保存状态").getByRole("status")).not.toHaveText("正在读取已保存进度")
  await training.getByRole("button", { name: "判断", exact: true }).click()
  await expect(review.getByText("原判已更正，已按原作答位置回算当前完整历史", { exact: true })).toBeVisible({timeout:15000})
  await expect(review.getByRole("button", { name: "申请一次评分复核" })).toHaveCount(0)
  expect(submitted).toBe(1)
  const feedback = page.getByRole("region", { name: "本次反馈" })
  await expect(feedback.getByText("尚未证明掌握", {exact:true})).toBeVisible()
  await expect(review.getByText(/j1：通过/)).toBeVisible()
  await review.getByText("查看复核引用的原答与来源", {exact:true}).click()
  await expect(review.getByText(/原答：确认可能丢失/)).toBeVisible()
  await review.screenshot({path:"test-results/review-320.png"})
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
  await review.getByRole("button", {name:"读取已有复核"}).scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await review.screenshot({path:"test-results/review-200.png"})
  await page.evaluate(() => { document.documentElement.style.fontSize = "" })
  page.once("dialog", dialog => dialog.accept())
  await page.getByRole("button", {name:"删除配置及 Key",exact:true}).click()
  await expect(page.getByText("配置及 Key 已删除，旧版本不能发起新调用。", {exact:true})).toBeVisible()
  await review.getByRole("button", {name:"读取已有复核"}).click()
  await expect(review.getByText(/原判已更正/).first()).toBeVisible()
  expect(errors).toEqual([])
})
