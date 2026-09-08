import { expect, test } from "@playwright/test"

test("administrator copies invitation; guest registers and cannot train; revoke persists", async ({
  browser,
}) => {
  const admin = await browser.newContext({
    permissions: ["clipboard-read", "clipboard-write"],
  })
  const page = await admin.newPage()
  await page.goto("/")
  await page
    .getByLabel("邮箱", { exact: true })
    .fill(process.env.FIRST_SUPERUSER!)
  await page
    .getByLabel("密码（12–128 字符）")
    .fill(process.env.FIRST_SUPERUSER_PASSWORD!)
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page.getByRole("heading", { name: "邀请管理" })).toBeVisible()
  await page.getByRole("button", { name: "生成邀请码" }).click()
  const first = page.locator("article").first()
  await expect(first).toContainText("未使用")
  const code = await first.locator("code").innerText()
  await first.getByRole("button", { name: "复制", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("邀请码已复制")
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(code)
  const guest = await browser.newContext({
    viewport: { width: 320, height: 800 },
  })
  const signup = await guest.newPage()
  await signup.goto("/")
  await signup.getByRole("button", { name: "使用邀请码注册" }).click()
  const email = `browser-${crypto.randomUUID()}@example.com`
  await signup.getByLabel("邮箱", { exact: true }).fill(email)
  await signup
    .getByLabel("密码（12–128 字符）")
    .fill("local-browser-test-password")
  await signup.getByLabel("邀请码", { exact: true }).fill(code)
  await signup.getByRole("button", { name: "注册", exact: true }).click()
  await expect(signup.getByRole("status")).toContainText("注册成功")
  await signup.getByRole("button", { name: "登录", exact: true }).click()
  await expect(signup.getByText(`${email} · 小白程序员`)).toBeVisible()
  await signup.getByRole("button", { name: "检查训练准入" }).click()
  await expect(signup.getByRole("status")).toHaveText("请先验证邮箱")
  await expect(signup.getByRole("heading", { name: "邀请管理" })).toHaveCount(0)
  expect(
    await signup.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.getByRole("button", { name: "刷新状态" }).click()
  await expect(page.locator("article").filter({ hasText: code })).toContainText(
    "已使用",
  )
  await page.getByRole("button", { name: "生成邀请码" }).click()
  await expect(first).toContainText("未使用")
  await first.getByRole("button", { name: "作废", exact: true }).click()
  await expect(first).toContainText("已作废")
  await page.reload()
  await expect(first).toContainText("已作废")
  await signup.screenshot({
    path: "test-results/invitation-account.png",
    fullPage: true,
  })
  await signup.getByRole("button", { name: "退出登录" }).click()
  await expect(signup.getByRole("status")).toHaveText("已退出当前设备")
  expect(
    await signup.evaluate(() => sessionStorage.getItem("token")),
  ).toBeNull()
  await signup.getByLabel("邮箱", { exact: true }).fill(email)
  await signup.getByLabel("密码（12–128 字符）").fill("incorrect-test-password")
  const requestAfterLogout = signup.waitForRequest((request) =>
    request.url().endsWith("/api/v1/login/access-token"),
  )
  await signup.getByRole("button", { name: "登录", exact: true }).click()
  expect((await requestAfterLogout).headers().authorization).toBeUndefined()
  await expect(signup.getByRole("status")).toHaveText("邮箱或密码错误")
  await admin.close()
  await guest.close()
})
