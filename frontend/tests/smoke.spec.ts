import { expect, test, type Page } from "@playwright/test";

async function expectNoHorizontalOverflow(page: Page) {
  const geometry = await page.evaluate(() => ({
    body: document.body.scrollWidth,
    root: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(Math.max(geometry.body, geometry.root)).toBeLessThanOrEqual(geometry.viewport + 1);
}

function contrastRatio(foreground: string, background: string) {
  const luminance = (hex: string) => {
    const channels = hex.match(/[a-f\d]{2}/gi)?.map((value) => Number.parseInt(value, 16) / 255) || [];
    const [red = 0, green = 0, blue = 0] = channels.map((value) =>
      value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    );
    return red * 0.2126 + green * 0.7152 + blue * 0.0722;
  };
  const first = luminance(foreground);
  const second = luminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

async function expectReadableTheme(page: Page) {
  const colors = await page.evaluate(() => {
    const styles = getComputedStyle(document.documentElement);
    const value = (name: string) => styles.getPropertyValue(name).trim();
    return {
      accent: value("--athar-accent"),
      canvas: value("--athar-parchment"),
      faint: value("--athar-ink-faint"),
      gold: value("--athar-gold"),
      onAccent: value("--athar-on-accent"),
      soft: value("--athar-ink-soft"),
      surface: value("--athar-surface"),
    };
  });
  for (const foreground of [colors.accent, colors.faint, colors.gold, colors.soft]) {
    expect(contrastRatio(foreground, colors.canvas)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(foreground, colors.surface)).toBeGreaterThanOrEqual(4.5);
  }
  expect(contrastRatio(colors.onAccent, colors.accent)).toBeGreaterThanOrEqual(4.5);
}

test("landing exposes the migrated paths", async ({page}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", {level: 1})).toContainText("تجويد الحروف");
  await expect(page.getByRole("link", {name: "تثبيت", exact: true})).toHaveAttribute("href", "/memorize");
  await expect(page.getByRole("link", {name: "مُكْث", exact: true})).toHaveAttribute("href", "/waqf");
  const paths = page.getByRole("region", {name: "من الدليل إلى القراءة اليومية."});
  await expect(paths.getByRole("link", {name: /تثبيت/})).toHaveAttribute("href", "/memorize?surah=2&from=255&to=257");
  await expect(paths.getByRole("link", {name: /مُكْث/})).toHaveAttribute("href", "/waqf?surah=2&ayah=255");
  await expectNoHorizontalOverflow(page);
  const themeToggle = page.locator('button[title^="الوضع"]');
  const themes = ["light", "sepia", "dark"];
  for (const [index, theme] of themes.entries()) {
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expectReadableTheme(page);
    if (index < themes.length - 1) await themeToggle.click();
  }
  await themeToggle.click();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.getByRole("link", {name: "المصحف", exact: true}).click();
  await expect(page).toHaveURL(/\/read(?:\?|$)/);
  await expect(page.getByRole("link", {name: "المصحف", exact: true})).toHaveAttribute("aria-current", "page");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});

test("Reader loads Quran, study tools, and timed audio", async ({page}) => {
  await page.goto("/read?surah=2&ayah=256");
  await expect(page.locator(".mushaf-word.is-focus").first()).toBeVisible();
  await expect(page.getByRole("button", {name: "المتشابهات"})).toBeVisible();
  await expect(page.getByRole("button", {name: "سبب النزول"})).toBeVisible();
  const studyTrigger = page.getByRole("button", {name: "أدوات الدراسة", exact: true});
  await expect(studyTrigger).not.toHaveAttribute("aria-controls");
  await studyTrigger.click();
  await expect(studyTrigger).toHaveAttribute("aria-controls", "reader-study-drawer");
  await expect(page.getByRole("dialog").getByRole("link", {name: /تثبيت/})).toHaveAttribute("href", "/memorize?surah=2&from=256&to=256");
  const closeStudy = page.getByRole("dialog").getByRole("button", {name: "إغلاق أدوات الدراسة"});
  await expect(closeStudy).toBeFocused();
  await closeStudy.click();
  await expect(studyTrigger).toBeFocused();
  await expect(page.getByRole("region", {name: "مشغّل التلاوة"})).toBeVisible();
  await expect(page.locator("audio")).toHaveAttribute("src", /002\.mp3|audio-proxy/);
  await expect(page.getByRole("button", {name: "تشغيل التلاوة"})).toBeEnabled();
  await expectNoHorizontalOverflow(page);
});

test("مُكْث compares evidence and builds a playable breath plan", async ({page}) => {
  await page.goto("/waqf?surah=2&ayah=255");
  await expect(page.getByRole("heading", {level: 1, name: "علامة المصحف، ووقف القارئ، وقول الإمام."})).toBeVisible();
  const waqfGuide = page.getByRole("navigation", {name: "محاور مُكْث"});
  await expect(waqfGuide.getByRole("link", {name: "موضع الوقف", exact: true})).toHaveAttribute("href", "#waqf-verse-title");
  await expect(waqfGuide.getByRole("link", {name: "قارن الشهادات", exact: true})).toHaveAttribute("href", "#waqf-comparison-title");
  await expect(page.locator(".waqf-word-unit")).toHaveCount(50, {timeout: 15_000});
  await expect(page.locator(".waqf-inline-stop").first()).toBeVisible();
  await expect(page.getByLabel("سعة النفس").getByRole("button", {name: "متوسط"})).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("القارئ المختار")).toBeEnabled();
  const firstPhrase = page.getByLabel("مقاطع القارئ").getByRole("button").first();
  await expect(firstPhrase).toBeEnabled();
  await firstPhrase.evaluate((button: HTMLButtonElement) => button.click());
  await expect(page.getByLabel("مساحة مُكْث لدراسة الوقف").locator("audio")).toHaveAttribute("src", /.+/);
  await expect(page.getByRole("tab", {selected: true})).toBeVisible();
  await expect(page.getByRole("heading", {name: "علامات المصاحف"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "وقوف القرّاء"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "قول الإمام", exact: true})).toBeVisible();
  await expect(page.getByRole("link", {name: "مختبر الوقف", exact: true})).toHaveAttribute("href", /waqf-lab/);
  await expect(page.getByRole("link", {name: "قارن الشهادات ↓", exact: true})).toHaveAttribute("href", "#waqf-comparison-title");
  const shortBreath = page.getByLabel("سعة النفس").getByRole("button", {name: "قصير"});
  await shortBreath.evaluate((button: HTMLButtonElement) => button.click());
  await expect(shortBreath).toHaveAttribute("aria-pressed", "true");
  await expectNoHorizontalOverflow(page);
});

test("تثبيت loads a range, conceal mode, context, and repetition", async ({page}) => {
  await page.goto("/memorize?surah=2&from=255&to=257");
  await expect(page.getByRole("heading", {level: 1, name: "كرّر، أخفِ، ثم استحضر."})).toBeVisible();
  await expect(page.locator(".mushaf-word.is-focus").first()).toBeVisible();
  await expect(page.locator(".mushaf-word.is-current").first()).toBeVisible();
  await expect(page.locator(".mushaf-word.is-context").first()).toBeVisible();
  await expect(page.getByText("البقرة · ٢٥٥–٢٥٧")).toBeVisible();
  await expect(page.getByRole("button", {name: "بدء جلسة التثبيت"})).toBeEnabled();
  await expect(page.getByLabel("جلسة التكرار").locator("audio")).toHaveAttribute("src", /002\.mp3|audio-proxy/);
  await page.locator("summary").filter({hasText: "إعدادات وخطة الجلسة"}).click();
  const sessionPlan = page.getByLabel("خطة جلسة التثبيت", {exact: true});
  await expect(sessionPlan).toContainText("ربط");
  await expect(page.getByLabel("تكرار الربط")).toBeEnabled();
  await expect(page.getByLabel("ربط تراكمي")).toBeChecked();
  await expect(page.getByLabel("قسّم حسب الوقف")).toBeChecked();
  await expect(page.getByRole("button", {name: "الخطوة التالية"})).toBeEnabled();
  await page.getByRole("button", {name: "الخطوة التالية"}).click();
  await expect(sessionPlan.locator("strong").first()).toContainText("٢ من");
  await page.getByLabel("ربط تراكمي").uncheck();
  await expect(page.getByLabel("تكرار الربط")).toBeDisabled();
  await expect(sessionPlan).not.toContainText("ربط تراكمي");
  await page.getByLabel("ربط تراكمي").check();
  await page.getByLabel("قسّم حسب الوقف").uncheck();
  await expect(sessionPlan).toContainText("آيات كاملة");
  await page.getByLabel("قسّم حسب الوقف").check();
  await page.getByRole("button", {name: "اختبر حفظي"}).click();
  await expect(page.locator(".mushaf-word.is-concealed").first()).toBeVisible();
  await expect(page.getByLabel("التفصيل الموضوعي")).not.toContainText("جارٍ");
  await expectNoHorizontalOverflow(page);
});
