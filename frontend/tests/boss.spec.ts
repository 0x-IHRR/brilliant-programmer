import { expect, test } from "@playwright/test"

test("首阶段标准先展示、三项原答保留、失败补练与首次晋升仅一次", async ({ page, request }) => {
  test.skip(!process.env.BOSS_BROWSER_TOKEN, "由 boss_browser.py 提供合成100点与真实worker")
  const token = process.env.BOSS_BROWSER_TOKEN!
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.setViewportSize({ width: 320, height: 760 })
  await page.goto("/?boss=1")
  await page.evaluate(t => sessionStorage.setItem("token", t), token)
  await page.reload()
  const entry = page.getByRole("region", { name: "首阶段Boss入口" })
  const training = page.getByRole("region", { name: "随机第一关" })
  const result = page.getByRole("region", { name: "Boss结算与晋升" })
  let first = ""
  for (const wrong of [true, false]) {
    await expect(entry.getByText("服务器当前等级：小白程序员 · 累计修为：" + (wrong ? "100" : "110"), { exact: true })).toBeVisible()
    for (const id of ["boss-chain", "boss-cause", "boss-verify"]) await expect(entry.getByText(new RegExp(`必考判断 ${id}`))).toBeVisible()
    const launch = entry.getByRole("button", { name: "主动开始首阶段Boss（独立新案例）", exact: true })
    await expect(launch).toBeDisabled()
    await entry.getByRole("checkbox").check()
    await launch.focus(); await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/training_run=/)
    const id = new URL(page.url()).searchParams.get("training_run")!
    if (wrong) first = id
    else expect(id).not.toBe(first)
    await expect(training.getByText("保存失败的三个独立判断", { exact: true })).toBeVisible({ timeout: 15000 })
    await expect(training.getByLabel("草稿保存状态").getByRole("status")).not.toHaveText("正在读取已保存进度")
    await training.getByRole("button", { name: "判断", exact: true }).click()
    const fieldsets = training.locator("fieldset").filter({ has: page.getByRole("textbox", { name: "这一判断的理由", exact: true }) })
    const reasons = training.getByRole("textbox", { name: "这一判断的理由", exact: true })
    await expect(reasons).toHaveCount(3)
    for (let i = 0; i < 3; i++) {
      const radio = fieldsets.nth(i).getByRole("radio").nth(wrong && i === 1 ? 1 : 0)
      await expect(radio).toBeEnabled(); await radio.focus(); await page.keyboard.press("Space"); await expect(radio).toBeChecked()
      await reasons.nth(i).fill("依据本项材料中的观察，选择对应查证行动。")
    }
    await expect(training.getByLabel("草稿保存状态").getByRole("status")).toHaveText("草稿已保存")
    await page.reload()
    await expect(reasons.nth(2)).toHaveValue("依据本项材料中的观察，选择对应查证行动。")
    await training.getByText(/允许将当前公开题面与作答发送给此模型检查相关性/).click()
    await training.getByRole("button", { name: "正式交卷", exact: true }).click()
    if (wrong) {
      await expect(result.getByText("本次确认了具体短板，保留原等级与历史", { exact: true })).toBeVisible({ timeout: 15000 })
      await expect(result.getByRole("link", { name: "针对 frontend.state 补练或主动检验", exact: true })).toBeVisible()
      await expect(result.getByText(/本轮首次晋升已保存/)).toHaveCount(0)
      await result.screenshot({ path: "test-results/boss-shortfall-320.png" })
      await result.getByRole("link", { name: "返回Boss入口，查看标准或主动新题重试", exact: true }).click()
    } else {
      await expect(result.getByText(/本轮首次晋升已保存/)).toBeVisible({ timeout: 15000 })
      await expect(training.getByText(/不直接更新等级/)).toHaveCount(0)
      await expect(result.getByText("服务器当前等级：初级程序员 · 累计修为：120", { exact: true })).toBeVisible()
      await expect(page.getByText(/@.* · 初级程序员/, { exact: false })).toBeVisible()
      await result.screenshot({ path: "test-results/boss-promotion-320.png" })
      await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
      await result.getByRole("button", { name: "重新读取Boss结论" }).scrollIntoViewIfNeeded()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await result.screenshot({ path: "test-results/boss-promotion-200.png" })
      await page.reload()
      await expect(result.getByText(/本轮首次晋升已保存/)).toBeVisible()
      const old = await (await request.get(`/api/v1/boss/tasks/${first}`, { headers: { Authorization: `Bearer ${token}` } })).json()
      expect(old.decision.outcome).toBe("evidenced_fail")
      expect(old.decision.shortfalls).toHaveLength(1)
      expect(old.current_level).toBe("初级程序员")
    }
  }
  expect(errors).toEqual([])
})
