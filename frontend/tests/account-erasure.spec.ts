import { expect, test } from "@playwright/test"
const cases: { token: string; owner: string; run: string; other: string; email: string }[] = JSON.parse(process.env.ACCOUNT_ERASURE_CASES ?? "[]")
for (const [index, mode] of ["lost-response", "other-account"].entries()) {
  test(`注销实际回执与跨会话隔离：${mode}`, async ({ page }) => {
    test.skip(!cases.length, "由 account_erasure_browser.py 提供真实合成账号")
    const item = cases[index]
    await page.setViewportSize({ width: 320, height: 780 })
    await page.goto("/")
    await page.evaluate(token => sessionStorage.setItem("token", token), item.token)
    await page.goto(`/?training_run=${item.run}`)
    const training = page.getByRole("region", { name: "随机第一关" })
    await expect(training.getByText("比较请求证据", { exact: true })).toBeVisible()
    const erasure = page.getByRole("region", { name: "注销账号", exact: true })
    await erasure.getByLabel("重新输入当前密码").fill("local-test-password-only")
    await erasure.getByRole("button", { name: "重新认证并查看注销范围" }).click()
    const final = erasure.getByRole("button", { name: "最终确认注销本账号" })
    await expect(final).toBeDisabled()
    await expect(erasure).toContainText("不能撤销")
    await expect(erasure).toContainText("不保留等级或奖励档案")
    await erasure.getByRole("checkbox").focus()
    await page.keyboard.press("Space")
    await expect(final).toBeEnabled()
    await final.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `test-results/account-${mode}-320.png` })
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%" })
    await final.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/account-${mode}-200.png` })
    await page.evaluate(() => { document.documentElement.style.fontSize = "" })
    let received!: () => void, release!: () => void
    const committed = new Promise<void>(resolve => { received = resolve })
    const held = new Promise<void>(resolve => { release = resolve })
    await page.route("**/account-erasure/*/confirm", async route => {
      const response = await route.fetch()
      expect(response.status()).toBe(202)
      expect((await response.json()).accepted_at).toBeTruthy()
      received()
      if (mode === "lost-response") await route.abort("failed")
      else { await held; await route.fulfill({ response }) }
    })
    await final.focus()
    await page.keyboard.press("Enter")
    await committed
    if (mode === "lost-response") {
      await expect(erasure.getByRole("alert")).toContainText("尚未确认")
      await page.reload()
      await expect(page.getByRole("button", { name: "登录", exact: true })).toBeVisible()
      await expect.poll(() => page.evaluate(() => sessionStorage.getItem("token"))).toBeNull()
      await expect(training).toHaveCount(0)
      await erasure.getByRole("button", { name: "读取实际注销回执" }).click()
      await expect(erasure.getByRole("status")).toContainText("注销")
      await expect.poll(() => new URL(page.url()).searchParams.has("training_run")).toBe(false)
    } else {
      await page.getByRole("button", { name: "退出登录", exact: true }).click()
      await page.getByLabel("邮箱", { exact: true }).fill(item.email)
      await page.getByLabel("密码（12–128 字符）", { exact: true }).fill("local-test-password-only")
      await page.getByRole("button", { name: "登录", exact: true }).click()
      await expect(page.getByText(item.email, { exact: false }).first()).toBeVisible()
      const tokenB = await page.evaluate(() => sessionStorage.getItem("token"))
      expect(tokenB).toBeTruthy()
      expect(tokenB).not.toBe(item.token)
      release()
      await expect(page.getByText(item.email, { exact: false }).first()).toBeVisible()
      expect(await page.evaluate(() => sessionStorage.getItem("token"))).toBe(tokenB)
      await expect(erasure).not.toContainText(item.owner)
    }
    const capability = await page.evaluate(() => JSON.parse(sessionStorage.getItem("account-erasure-receipt")!))
    await expect.poll(async () => {
      const response = await page.request.post(`/api/v1/account-erasure/${capability.request}/status`, { data: { receipt_key: capability.key } })
      expect(response.status()).toBe(200)
      return (await response.json()).completed_at
    }).toBeTruthy()
    if (mode === "lost-response") {
      await erasure.getByRole("button", { name: "读取实际注销回执" }).click()
      await expect(erasure.getByRole("status")).toHaveText("注销资料清除已完成")
      await erasure.getByRole("button", { name: "读取实际注销回执" }).click()
      await expect(erasure.getByRole("status")).toHaveText("注销资料清除已完成")
      await page.screenshot({ path: "test-results/account-completed-320.png" })
    } else {
      await page.evaluate(() => {
        const original = Storage.prototype.setItem
        Storage.prototype.setItem = function(key, value) {
          if (key === "account-erasure-receipt") throw new DOMException("controlled storage full", "QuotaExceededError")
          return original.call(this, key, value)
        }
      })
      await erasure.getByLabel("重新输入当前密码").fill("local-test-password-only")
      await erasure.getByRole("button", { name: "重新认证并查看注销范围" }).click()
      await expect(erasure.getByRole("alert")).toContainText("恢复凭据未能保存")
      await expect(erasure.getByRole("button", { name: "最终确认注销本账号" })).toHaveCount(0)
      await expect(page.getByText(item.email, { exact: false }).first()).toBeVisible()
    }
  })
}

const extras: { mode: string; token: string; owner: string; email: string; verification: string }[] = JSON.parse(process.env.ACCOUNT_ERASURE_EXTRAS ?? "[]")
for (const extra of extras) {
  test(`注销后旧 ${extra.mode} 成功响应不恢复私有页面`, async ({ page }) => {
    await page.goto("/")
    await page.evaluate(token => sessionStorage.setItem("token", token), extra.token)
    await page.goto(extra.mode === "verify" ? `/?account_erasure_test=verify#verify=${extra.verification}` : "/")
    await expect(page.getByText(extra.email, { exact: false }).first()).toBeVisible()
    const erasure = page.getByRole("region", { name: "注销账号", exact: true })
    await erasure.getByLabel("重新输入当前密码").fill("local-test-password-only")
    await erasure.getByRole("button", { name: "重新认证并查看注销范围" }).click()
    await expect(erasure.getByRole("checkbox")).toBeVisible()
    if (extra.mode === "me") await page.getByRole("button", { name: "退出登录", exact: true }).click()
    let received!: () => void, release!: () => void, finished!: () => void
    const committed = new Promise<void>(resolve => { received = resolve })
    const held = new Promise<void>(resolve => { release = resolve })
    const delivered = new Promise<void>(resolve => { finished = resolve })
    await page.route(extra.mode === "me" ? "**/users/me" : "**/users/me/verify-email", async route => {
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      received()
      await held
      await route.fulfill({ response })
      finished()
    })
    if (extra.mode === "me") {
      await page.getByLabel("邮箱", { exact: true }).fill(extra.email)
      await page.getByLabel("密码（12–128 字符）", { exact: true }).fill("local-test-password-only")
      await page.getByRole("button", { name: "登录", exact: true }).click()
    } else await page.getByRole("button", { name: "确认验证邮箱", exact: true }).click()
    await committed
    const cap = await page.evaluate(() => JSON.parse(sessionStorage.getItem("account-erasure-receipt")!))
    const confirmation = await page.request.post(`/api/v1/account-erasure/${cap.request}/confirm`, { data: { receipt_key: cap.key, confirmation: "注销本账号并永久删除全部私有资料" } })
    expect(confirmation.status()).toBe(202)
    await erasure.getByRole("button", { name: "读取实际注销回执" }).click()
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem("token"))).toBeNull()
    release()
    await delivered
    await expect(page.getByRole("button", { name: "登录", exact: true })).toBeVisible()
    await expect(page.getByRole("button", { name: "退出登录", exact: true })).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem("token"))).toBeNull()
    await expect.poll(async () => (await (await page.request.post(`/api/v1/account-erasure/${cap.request}/status`, { data: { receipt_key: cap.key } })).json()).completed_at).toBeTruthy()
  })
}
