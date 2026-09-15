import { expect, test } from "@playwright/test";

test("Madinah QVP edition draws a printed canvas and keeps the picker", async ({page}) => {
  await page.goto("/read?surah=1&ayah=1&view=page&edition=madinah_qvp&layout=single");
  await expect(page.locator(".reader-page.edition-madinah_qvp")).toBeVisible({timeout: 20_000});
  const canvas = page.locator("canvas.qvp-page-canvas").first();
  await expect(canvas).toBeVisible({timeout: 20_000});
  await expect.poll(async () => canvas.evaluate((node) => {
    const canvasNode = node as HTMLCanvasElement;
    if (canvasNode.width < 80 || canvasNode.height < 80) return 0;
    const ctx = canvasNode.getContext("2d");
    if (!ctx) return 0;
    const {data} = ctx.getImageData(0, 0, canvasNode.width, canvasNode.height);
    let ink = 0;
    for (let index = 0; index < data.length; index += 16) {
      const red = data[index];
      const green = data[index + 1];
      const blue = data[index + 2];
      const alpha = data[index + 3];
      if (alpha > 10 && (red + green + blue) < 600) ink += 1;
    }
    return ink;
  }), {timeout: 20_000}).toBeGreaterThan(40);
  await expect(page.locator(".reader-page.edition-madinah_qvp .mushaf-foot")).toContainText("مطابق للمطبوع");
});

test("QVP can hide printed waqf and overlay another mushaf", async ({page, isMobile}) => {
  await page.goto("/read?surah=2&ayah=255&view=page&edition=madinah_qvp&layout=single");
  await expect(page.locator("canvas.qvp-page-canvas").first()).toBeVisible({timeout: 20_000});
  if (isMobile) {
    await page.getByRole("button", {name: "إعدادات القراءة", exact: true}).click();
    await expect(page.getByRole("dialog", {name: "إعدادات القراءة"})).toBeVisible();
  } else {
    await page.getByRole("button", {name: "المزيد من إعدادات القراءة"}).click();
    await expect(page.getByRole("dialog", {name: "إعدادات القراءة"})).toBeVisible();
  }
  await page.getByRole("radio", {name: "الأزهر"}).click();
  await expect(page.locator(".qvp-waqf-layer .qvp-pause-slot").first()).toBeVisible({timeout: 15_000});
  await page.getByRole("checkbox", {name: "إظهار علامات الوقف"}).uncheck();
  await expect(page.locator(".qvp-waqf-layer .qvp-pause-slot")).toHaveCount(0);
});
