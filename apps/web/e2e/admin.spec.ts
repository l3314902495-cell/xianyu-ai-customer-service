import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("用户名或邮箱").fill("admin");
  await page.getByLabel("密码", { exact: true }).fill("Admin123!");
  await page.getByRole("button", { name: /登录后台/ }).click();
  await expect(page).toHaveURL(/\/$/);
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("商品抽屉支持键盘标签页、焦点恢复与脏数据保护", async ({ page }) => {
  await page.goto("/products");
  const trigger = page.getByRole("button", { name: /编辑/ }).first();
  await trigger.click();

  const drawer = page.getByRole("dialog").last();
  await expect(drawer).toBeVisible();
  await expect(drawer.locator(":focus")).toHaveCount(1);

  const firstTab = drawer.getByRole("tab").first();
  await firstTab.focus();
  await firstTab.press("ArrowRight");
  await expect(drawer.getByRole("tab").nth(1)).toHaveAttribute("aria-selected", "true");

  await drawer.getByRole("tab", { name: /基本信息/ }).click();
  await drawer.getByLabel("商品名称").fill("尚未保存的商品名称");
  await page.keyboard.press("Escape");
  const warning = page.getByRole("alertdialog", { name: "放弃未保存的修改？" });
  await expect(warning).toBeVisible();
  await warning.getByRole("button", { name: "取消" }).click();
  await expect(drawer).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).include("[role=dialog]").analyze();
  expect(accessibility.violations.filter((item) => item.impact === "critical")).toEqual([]);

  await page.getByRole("button", { name: "关闭商品编辑" }).click();
  await page.getByRole("alertdialog", { name: "放弃未保存的修改？" }).getByRole("button", { name: "放弃修改" }).click();
  await expect(drawer).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("商品页通过基础无障碍扫描", async ({ page }) => {
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "商品管理" })).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter((item) => ["critical", "serious"].includes(item.impact || ""))).toEqual([]);
});
