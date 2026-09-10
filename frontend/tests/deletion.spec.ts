import { expect, test } from "@playwright/test"

const cases: { token: string, run: string, other: string }[] = JSON.parse(process.env.DELETION_BROWSER_CASES ?? "[]")
for (const [index, mode] of ["lost-response", "changed-selection"].entries()) {
  test(`永久删除完成清除同页私有投影：${mode}`, async ({ page }) => {
    test.skip(!cases.length, "由 deletion_browser.py 提供真实合成记录")
    const item = cases[index]
    await page.setViewportSize({ width: 320, height: 780 })
    await page.goto("/")
    await page.evaluate(token => sessionStorage.setItem("token", token), item.token)
    await page.goto(`/?training_run=${item.run}`)
    const training = page.getByRole("region", { name: "随机第一关" })
    await expect(training.getByText("比较请求证据", { exact: true })).toBeVisible()
    const records = page.getByRole("region", { name: "我的记录与资料管理" })
    await records.getByRole("button", { name: "读取本人记录", exact: true }).click()
    await records.getByLabel("选择管理记录").selectOption(`training:${item.run}`)
    await records.getByLabel("删除重新认证密码").fill("local-test-password-only")
    await records.getByRole("button", { name: "重新认证并预览影响，不执行删除" }).click()
    const impact = records.getByLabel("最终删除影响范围")
    await expect(impact).toContainText(item.run)
    await expect(impact).toContainText("后续独立检验会明确退出")
    const final = records.getByRole("button", { name: "最终确认永久删除，无法撤销" })
    await expect(final).toBeDisabled()
    await records.getByRole("checkbox").focus()
    await page.keyboard.press("Space")
    await expect(final).toBeEnabled()
    await impact.screenshot({ path: `test-results/deletion-${mode}-320.png` })
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
    await final.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/deletion-${mode}-200.png` })
    await page.evaluate(() => { document.documentElement.style.fontSize = "" })
    let received!: () => void
    const committed = new Promise<void>(resolve => { received = resolve })
    let release!: () => void
    const hold = new Promise<void>(resolve => { release = resolve })
    await page.route("**/records/deletions/*/confirm", async route => {
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      expect((await response.json()).completed_at).toBeTruthy()
      received()
      if (mode === "lost-response") await route.abort("failed")
      else { await hold; await route.fulfill({ response }) }
    })
    await final.focus()
    await page.keyboard.press("Enter")
    await committed
    expect(new URL(page.url()).searchParams.get("training_run")).toBe(item.run)
    if (mode === "lost-response") {
      await expect(records.getByRole("alert")).toContainText("操作结果尚未确认")
      await records.getByRole("button", { name: "读取删除实际状态" }).click()
    } else {
      await records.getByLabel("选择管理记录").selectOption(`training:${item.other}`)
      await expect(records.getByLabel("选择管理记录")).toHaveValue(`training:${item.other}`)
      release()
    }
    await expect.poll(() => new URL(page.url()).searchParams.has("training_run")).toBe(false)
    await expect(training.getByText("比较请求证据", { exact: true })).toHaveCount(0)
    await records.getByRole("button", { name: "读取删除实际状态" }).click()
    await expect(records.getByRole("status")).toContainText("完成永久删除")
    // The known completed receipt is readable without repeatedly reloading.
    await expect(records.getByRole("status")).toBeVisible()
    await page.screenshot({ path: `test-results/deletion-${mode}-completed.png` })
  })
}
