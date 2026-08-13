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
      negative: value("--athar-negative"),
      positive: value("--athar-positive"),
      soft: value("--athar-ink-soft"),
      surface: value("--athar-surface"),
    };
  });
  for (const foreground of [colors.accent, colors.faint, colors.gold, colors.negative, colors.positive, colors.soft]) {
    expect(contrastRatio(foreground, colors.canvas)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(foreground, colors.surface)).toBeGreaterThanOrEqual(4.5);
  }
  expect(contrastRatio(colors.onAccent, colors.accent)).toBeGreaterThanOrEqual(4.5);
}

async function expectThemeCycle(page: Page) {
  const themeToggle = page.locator('button[title^="الوضع"]');
  const themes = ["light", "sepia", "dark"];
  for (const [index, theme] of themes.entries()) {
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expectReadableTheme(page);
    if (index < themes.length - 1) await themeToggle.click();
  }
  await themeToggle.click();
}

async function openMobileReaderSettings(page: Page) {
  const trigger = page.getByRole("button", {name: "إعدادات القراءة", exact: true});
  if (!(await trigger.isVisible())) return false;
  await trigger.click();
  await expect(page.getByRole("dialog", {name: "إعدادات القراءة"})).toBeVisible();
  return true;
}

test("landing exposes the migrated paths", async ({page}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", {level: 1})).toContainText("تجويد الحروف");
  await expect(page.getByRole("link", {name: "تثبيت", exact: true})).toHaveAttribute("href", "/memorize");
  await expect(page.getByRole("link", {name: "مُكْث", exact: true})).toHaveAttribute("href", "/waqf");
  await expect(page.getByRole("link", {name: "تدريب", exact: true})).toHaveAttribute("href", "/waqf-practice");
  const paths = page.getByRole("region", {name: "من الدليل إلى القراءة اليومية."});
  await expect(paths.getByRole("link", {name: /تثبيت/})).toHaveAttribute("href", "/memorize?surah=2&from=255&to=257");
  await expect(paths.getByRole("link", {name: /مُكْث/})).toHaveAttribute("href", "/waqf?surah=2&ayah=255");
  await expect(paths.getByRole("link", {name: /تدريب/})).toHaveAttribute("href", "/waqf-practice?surah=2&from=255&to=255");
  await expectNoHorizontalOverflow(page);
  await expectThemeCycle(page);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.getByRole("link", {name: "المصحف", exact: true}).click();
  await expect(page).toHaveURL(/\/read(?:\?|$)/);
  await expect(page.getByRole("link", {name: "المصحف", exact: true})).toHaveAttribute("aria-current", "page");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});

test("Reader loads Quran, study tools, and timed audio", async ({page}) => {
  await page.goto("/read?surah=2&ayah=256");
  await expect(page.locator(".mushaf-word.is-focus").first()).toBeVisible({timeout: 15_000});
  await expect(page.locator(".mushaf-head-juz-glyph").first()).toHaveText(/[\ue001-\ue01e]/);
  await expect(page.locator(".mushaf-head-surah-glyph").first()).toHaveText(/[\ufb00-\ufcff]/);
  await expect.poll(() => page.evaluate(async () => {
    await Promise.all([
      document.fonts.load('16px "QCF Common"'),
      document.fonts.load('16px "Surah Names"'),
      document.fonts.load('24px "QCF Basmala"'),
    ]);
    return document.fonts.check('16px "QCF Common"')
      && document.fonts.check('16px "Surah Names"')
      && document.fonts.check('16px "QCF Basmala"');
  })).toBe(true);
  await expect.poll(() => page.locator('.mushaf-line[data-justify="true"] .mushaf-line-inner').first().evaluate((line) => {
    const spacing = Number.parseFloat(getComputedStyle(line).wordSpacing);
    return Number.isFinite(spacing) ? spacing : 0;
  })).toBeLessThanOrEqual(4.1);
  // Match the main app stretch ceiling (≤1.20 in dual). Measured font fit
  // should leave little residual scaleX; this guards against stringy glyphs.
  await expect.poll(() => page.locator('.mushaf-line[data-justify="true"] .mushaf-line-inner').evaluateAll((inners) => Math.max(
    ...inners.map((inner) => {
      const matrix = getComputedStyle(inner).transform.match(/^matrix\(([^,]+)/);
      const scale = matrix ? Number(matrix[1]) : 1;
      return Number.isFinite(scale) ? scale : 1;
    }),
  ))).toBeLessThanOrEqual(1.21);
  // After measured font fit, typical justified lines should already fill most
  // of the text column before residual scaleX (same contract as تثبيت).
  await expect.poll(() => page.locator('.mushaf-line[data-justify="true"]').evaluateAll((lines) => {
    const ratios = lines.map((line) => {
      const inner = line.querySelector<HTMLElement>(".mushaf-line-inner");
      if (!inner || !(line as HTMLElement).clientWidth) return 1;
      const matrix = getComputedStyle(inner).transform.match(/^matrix\(([^,]+)/);
      const scaleX = matrix ? Number(matrix[1]) : 1;
      const visualInner = inner.getBoundingClientRect().width;
      const visualLine = line.getBoundingClientRect().width;
      const layoutLine = (line as HTMLElement).clientWidth;
      const inherited = visualLine / layoutLine;
      const rendered = inherited > 0 ? visualInner / inherited : visualInner;
      const natural = scaleX > 0 ? rendered / scaleX : rendered;
      return natural / Math.max(1, layoutLine - 10);
    }).filter((ratio) => Number.isFinite(ratio));
    if (!ratios.length) return 0;
    ratios.sort((a, b) => a - b);
    return ratios[Math.floor(ratios.length / 2)] || 0;
  })).toBeGreaterThan(0.82);
  // Lines must stay inside the printed page (Madinah inset ≈10px + glyph overhang).
  await expect.poll(() => page.locator(".reader-page.is-page").evaluateAll((pages) => {
    let worst = 0;
    pages.forEach((pageEl) => {
      const pageRect = pageEl.getBoundingClientRect();
      pageEl.querySelectorAll<HTMLElement>(".mushaf-line-inner").forEach((inner) => {
        const rect = inner.getBoundingClientRect();
        worst = Math.max(worst, pageRect.left - rect.left, rect.right - pageRect.right);
      });
    });
    return worst;
  })).toBeLessThanOrEqual(2);

  const tajweedButton = page.getByRole("button", {name: "تلوين التجويد", exact: true});
  if (await tajweedButton.isVisible()) {
    await tajweedButton.click();
  } else {
    await openMobileReaderSettings(page);
    await page.getByRole("checkbox", {name: "تلوين أحكام التجويد"}).check();
    await page.getByRole("dialog", {name: "إعدادات القراءة"}).getByRole("button", {name: "إغلاق إعدادات القراءة"}).click();
  }
  await expect(page.locator(".reader-page[data-tajweed=true] .tajweed-rule").first()).toBeVisible({timeout: 15_000});
  await expect(page.getByRole("button", {name: "المتشابهات"})).toBeVisible();
  await expect(page.getByRole("button", {name: "سبب النزول"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "افهم ما تراه قبل أن تقرأ"})).toBeVisible();
  await expect(page.getByLabel("أهم رموز الوقف")).toContainText("لا تقف هنا");
  const studyTrigger = page.getByRole("button", {name: "أدوات الدراسة", exact: true});
  await expect(studyTrigger).not.toHaveAttribute("aria-controls");
  await studyTrigger.click();
  await expect(studyTrigger).toHaveAttribute("aria-controls", "reader-study-drawer");
  await expect(page.getByRole("dialog").getByRole("link", {name: /تثبيت/})).toHaveAttribute("href", "/memorize?surah=2&from=256&to=256");
  const closeStudy = page.getByRole("dialog").getByRole("button", {name: "إغلاق أدوات الدراسة"});
  await expect(closeStudy).toBeFocused();
  await closeStudy.click();
  await expect(studyTrigger).toBeFocused();
  const readerAudio = page.getByRole("region", {name: "مشغّل التلاوة"});
  await expect(readerAudio).toBeVisible();
  await expect(readerAudio.locator("audio")).toHaveAttribute("src", /002\.mp3|audio-proxy/);
  await expect(page.getByRole("button", {name: "تشغيل التلاوة"})).toBeEnabled();
  const mobileSettingsOpen = await openMobileReaderSettings(page);
  await page.getByRole("combobox", {name: "رسم الصفحة"}).selectOption("azhar_amiri");
  if (mobileSettingsOpen) await page.getByRole("dialog", {name: "إعدادات القراءة"}).getByRole("button", {name: "إغلاق إعدادات القراءة"}).click();
  await expect(page).toHaveURL(/edition=azhar_amiri/);
  const printedWaqfMark = page.locator(".reader-page.edition-azhar_amiri .mushaf-print-mark").first();
  await expect(printedWaqfMark).toBeVisible({timeout: 15_000});
  await expect(printedWaqfMark).toHaveText(/[ۖ-ۜ]/);
  await expect(page.locator(".reader-page.edition-azhar_amiri .mushaf-word").filter({hasText: /۝[٠-٩]+/}).first()).toBeVisible();
  await page.getByRole("button", {name: "افتح دليل التلاوة"}).click();
  await expect(page.getByRole("region", {name: "دليل التلاوة"})).toContainText("بصوت", {timeout: 15_000});
  await expect(page.getByLabel("مقاطع دليل التلاوة").getByRole("button").first()).toBeVisible();
  const mobileSettingsForShemrly = await openMobileReaderSettings(page);
  await page.getByRole("combobox", {name: "رسم الصفحة"}).selectOption("shamarly");
  if (mobileSettingsForShemrly) await page.getByRole("dialog", {name: "إعدادات القراءة"}).getByRole("button", {name: "إغلاق إعدادات القراءة"}).click();
  await expect(page.getByText("خط الشمرلي غير متوفر لهذه الصفحة بعد").first()).toBeVisible({timeout: 15_000});
  await expect(page.getByRole("link", {name: "شاهد صفحة مكتملة من الشمرلي"}).first()).toHaveAttribute("href", "/read?surah=11&ayah=121&view=page&edition=shamarly");
  await page.goto("/read?surah=11&ayah=121&view=page&edition=shamarly");
  await expect(page.locator(".reader-page.edition-shamarly .mushaf-lines").first()).toBeVisible({timeout: 15_000});
  await expect.poll(() => page.evaluate(() => document.fonts.check('16px "Shemrly-Page193"'))).toBe(true);
  await expectNoHorizontalOverflow(page);
});

test("Reader keeps the Mushaf first and navigates by page", async ({page}) => {
  await page.goto("/read?surah=2&ayah=256&view=page&edition=digital_khatt");
  const stage = page.getByRole("region", {name: /موضع القراءة/});
  await expect(stage).toBeVisible({timeout: 15_000});
  await expect(page.locator(".page-number").filter({hasText: "٤٢"})).toBeVisible();
  const desktopSpread = await page.evaluate(() => window.innerWidth >= 1100);
  if (desktopSpread) {
    await expect(stage).toHaveAttribute("data-page-count", "2");
    await expect(page.locator(".reader-mushaf-spread .reader-page")).toHaveCount(2);
    await expect(page.locator(".page-number").filter({hasText: "٤١"})).toBeVisible();
  } else {
    await expect(stage).toHaveAttribute("data-page-count", "1");
  }
  const geometry = await page.locator(".reader-page").first().evaluate((mushaf) => {
    const rect = mushaf.getBoundingClientRect();
    return {bottom: rect.bottom, height: rect.height, viewport: window.innerHeight};
  });
  // Dual spread shrinks each page; single-page mode keeps a taller card.
  expect(geometry.height).toBeGreaterThan(desktopSpread ? 280 : 420);
  // Dual chrome (spread gutter / stage padding) can sit a few px past the
  // strict single-page viewport contract while remaining on-screen.
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewport + (desktopSpread ? 20 : 1));

  await page.getByRole("button", {name: "الصفحة التالية"}).click();
  await expect(page.locator(".page-number").filter({hasText: "٤٣"})).toBeVisible({timeout: 15_000});
  if (desktopSpread) await expect(page.locator(".page-number").filter({hasText: "٤٤"})).toBeVisible();
  await expect(page).toHaveURL(/ayah=257/);
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".page-number").filter({hasText: "٤٢"})).toBeVisible({timeout: 15_000});
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem("athar-reader-preferences"))).toBe("page:digital_khatt:dual");

  const mobileSettingsOpen = await openMobileReaderSettings(page);
  if (mobileSettingsOpen) {
    await expect(page.getByRole("combobox", {name: "السورة"})).toBeVisible();
    await page.getByRole("dialog", {name: "إعدادات القراءة"}).getByRole("button", {name: "إغلاق إعدادات القراءة"}).click();
  }
  await expectNoHorizontalOverflow(page);
});

test("مُكْث compares evidence and builds a playable breath plan", async ({page}) => {
  test.setTimeout(60_000);
  await page.goto("/waqf?surah=2&ayah=255");
  await expect(page.getByRole("heading", {level: 1, name: "علامة المصحف، ووقف القارئ، وقول الإمام."})).toBeVisible();
  await expect(page.getByText("— مُكْث", {exact: true})).toBeVisible();
  await expect(page.getByRole("region", {name: "اختيار موضع الدراسة"})).toBeVisible();
  await expect(page.getByRole("link", {name: "تدرّب على هذا الموضع", exact: true}).first()).toHaveAttribute("href", /waqf-practice/);
  await expect(page.locator(".waqf-word-unit")).toHaveCount(50, {timeout: 15_000});
  await expect(page.locator(".waqf-inline-stop").first()).toBeVisible();
  await expect(page.locator(".waqf-symbol").first()).toHaveText(/[ۖ-ۜ]/);
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
  await expect(page.getByRole("heading", {name: "مصفوفة المصاحف والقرّاء"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "كل القرّاء"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "قول الأئمة في الآية"})).toBeVisible();
  const desktopMatrix = await page.evaluate(() => window.innerWidth > 900);
  if (desktopMatrix) {
    await expect(page.locator(".waqf-matrix")).toBeVisible();
    await expect(page.getByRole("button", {name: /استمع لـ/}).first()).toBeVisible();
  } else {
    await expect(page.locator(".waqf-matrix-card").first()).toBeVisible();
  }
  await expect(page.getByRole("link", {name: "مختبر الوقف", exact: true}).first()).toHaveAttribute("href", /waqf-lab/);
  await expect(page.getByRole("link", {name: "قارن الشهادات ↓", exact: true})).toHaveAttribute("href", "#waqf-comparison-title");
  await expect(page.getByRole("combobox", {name: "البحث عن آية"})).toBeVisible();
  await page.getByRole("combobox", {name: "البحث عن آية"}).fill("2:256");
  await page.getByRole("combobox", {name: "البحث عن آية"}).press("Enter");
  await expect(page).toHaveURL(/ayah=256/);
  await expect(page.getByRole("heading", {name: /الآية ٢٥٦/})).toBeVisible({timeout: 15_000});
  await page.getByRole("combobox", {name: "البحث عن آية"}).fill("الله");
  const searchResults = page.getByRole("listbox", {name: "نتائج البحث"});
  await expect(searchResults).toBeVisible({timeout: 15_000});
  await searchResults.getByRole("option").first().evaluate((option: HTMLElement) => option.click());
  await expect(page).toHaveURL(/ayah=\d+/);
  await expectThemeCycle(page);
  const shortBreath = page.getByLabel("سعة النفس").getByRole("button", {name: "قصير"});
  await shortBreath.evaluate((button: HTMLButtonElement) => button.click());
  await expect(shortBreath).toHaveAttribute("aria-pressed", "true");
  await expectNoHorizontalOverflow(page);
});

test("تثبيت loads a range, conceal mode, context, and repetition", async ({page}) => {
  test.setTimeout(60_000);
  await page.goto("/memorize?surah=2&from=255&to=257");
  await expect(page.getByRole("heading", {level: 1, name: "ثبّت حفظك."})).toBeVisible();
  await expect(page.getByText("— تثبيت", {exact: true})).toBeVisible();
  await expect(page.getByRole("region", {name: "استوديو التثبيت"})).toBeVisible();
  await expect(page.locator(".mushaf-word.is-focus").first()).toBeVisible();
  await expect(page.locator(".mushaf-word.is-current").first()).toBeVisible();
  await expect(page.locator(".mushaf-word.is-context").first()).toBeVisible();
  await expect(page.getByLabel("ملخص نطاق التثبيت").getByText("سورة البقرة · ٢٥٥–٢٥٧", {exact: true})).toBeVisible();
  await expect(page.getByRole("button", {name: "بدء جلسة التثبيت"})).toBeEnabled();
  await expect(page.getByLabel("شريط جلسة التثبيت")).toBeVisible();
  await expect(page.getByLabel("موضع جلسة التثبيت")).toBeVisible();
  await expect(page.getByLabel("جلسة التكرار").locator("audio")).toHaveAttribute("src", /002\.mp3|audio-proxy/);
  const noDocScroll = await page.evaluate(() => {
    const root = document.documentElement;
    return root.scrollHeight <= root.clientHeight + 2;
  });
  expect(noDocScroll).toBe(true);
  const word255 = page.locator('.mushaf-word[data-ayah="255"]').first();
  const word256 = page.locator('.mushaf-word[data-ayah="256"]').first();
  await word255.evaluate((word: HTMLElement) => word.click());
  await expect(page.getByText("اضغط آية النهاية لإكمال النطاق، أو Escape للإلغاء.")).toBeVisible();
  await expect(page.locator(".mushaf-word.is-range-draft").first()).toBeVisible();
  await word256.evaluate((word: HTMLElement) => word.click());
  await expect(page.getByLabel("ملخص نطاق التثبيت").getByText("سورة البقرة · ٢٥٥–٢٥٦", {exact: true})).toBeVisible();
  await page.getByRole("button", {name: "تكبير المصحف"}).click();
  await expect(page.getByLabel("مستوى التكبير")).toContainText("١١٠");
  await expect(page.locator(".reader-mushaf-stage")).toHaveAttribute("data-zoom", "1.1");
  await page.getByRole("button", {name: "ملاءمة"}).click();
  await expect(page.locator(".reader-mushaf-stage")).toHaveAttribute("data-zoom", "1.0");
  const desktopSpread = await page.evaluate(() => window.innerWidth >= 1100);
  if (desktopSpread) {
    await expect(page.getByRole("button", {name: "صفحتان متقابلتان"})).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".reader-mushaf-stage")).toHaveAttribute("data-page-count", "2");
    await expect(page.locator(".reader-mushaf-spread .reader-page")).toHaveCount(2);
  } else {
    await expect(page.locator(".reader-mushaf-stage")).toHaveAttribute("data-page-count", "1");
  }
  await page.getByRole("button", {name: "إعدادات الجلسة"}).click();
  const sessionPlan = page.getByLabel("خطة جلسة التثبيت", {exact: true});
  await expect(sessionPlan).toContainText("ربط");
  await expect(page.getByLabel("تكرار الربط")).toBeEnabled();
  await expect(page.getByLabel("ربط تراكمي")).toBeChecked();
  await expect(page.getByLabel("قسّم حسب الوقف")).toBeChecked();
  await expect(page.getByRole("button", {name: "الخطوة التالية"})).toBeEnabled();
  await page.getByRole("button", {name: "الخطوة التالية"}).evaluate((button: HTMLButtonElement) => button.click());
  await expect(sessionPlan.locator("strong").first()).toContainText("٢ من");
  await page.getByLabel("ربط تراكمي").evaluate((el: HTMLElement) => {
    const input = el instanceof HTMLInputElement ? el : el.querySelector("input");
    if (input instanceof HTMLInputElement && input.checked) input.click();
  });
  await expect(page.getByLabel("تكرار الربط")).toBeDisabled();
  await expect(sessionPlan).not.toContainText("ربط تراكمي");
  await page.getByLabel("ربط تراكمي").evaluate((el: HTMLElement) => {
    const input = el instanceof HTMLInputElement ? el : el.querySelector("input");
    if (input instanceof HTMLInputElement && !input.checked) input.click();
  });
  await page.getByLabel("قسّم حسب الوقف").evaluate((el: HTMLElement) => {
    const input = el instanceof HTMLInputElement ? el : el.querySelector("input");
    if (input instanceof HTMLInputElement && input.checked) input.click();
  });
  await expect(sessionPlan).toContainText("آيات كاملة");
  await page.getByLabel("قسّم حسب الوقف").evaluate((el: HTMLElement) => {
    const input = el instanceof HTMLInputElement ? el : el.querySelector("input");
    if (input instanceof HTMLInputElement && !input.checked) input.click();
  });
  await page.getByRole("button", {name: "اختبر حفظي"}).evaluate((button: HTMLButtonElement) => button.click());
  await expect(page.locator(".mushaf-word.is-concealed").first()).toBeVisible();
  await expect(page.getByLabel("التفصيل الموضوعي")).not.toContainText("جارٍ");
  await expect(page.getByLabel("التفصيل الموضوعي")).toContainText("التفصيل الموضوعي");
  await expect(page.locator(".mushaf-word.is-context").first()).toHaveAttribute("data-context-color", /^#/);
  await expectNoHorizontalOverflow(page);
});

test("تدريب grades tapped stops against the printed mushaf", async ({page}) => {
  await page.goto("/waqf-practice?surah=2&from=255&to=255");
  await expect(page.getByRole("heading", {level: 1, name: "علّم وقفك، وقيّمه بالمطبوع."})).toBeVisible();
  await expect(page.getByText("— تدريب", {exact: true})).toBeVisible();
  await expect(page.getByRole("region", {name: "إعدادات التدريب"})).toBeVisible();
  await expect(page.getByLabel("ملخص مقطع التدريب")).toContainText("سورة البقرة · ٢٥٥");
  await expect(page.locator(".practice-word")).toHaveCount(50, {timeout: 15_000});
  await expect(page.getByRole("button", {name: "قيّم وقوفي"})).toBeDisabled();
  await page.locator(".practice-word.is-end").last().click();
  await expect(page.getByRole("button", {name: "قيّم وقوفي"})).toBeEnabled();
  await page.getByRole("button", {name: "قيّم وقوفي"}).click();
  await expect(page.getByRole("heading", {name: "نتيجة التقييم"})).toBeVisible({timeout: 15_000});
  await expect(page.getByRole("img", {name: /نتيجة التقييم/})).toBeVisible();
  await expect(page.getByRole("link", {name: "ادرس هذا الموضع في مُكْث"})).toHaveAttribute("href", "/waqf?surah=2&ayah=255");
  await expect(page.getByRole("link", {name: "افتح التسجيل الصوتي"})).toHaveAttribute("href", /waqf-practice/);
  await expect(page.getByRole("link", {name: "تدريب", exact: true})).toHaveAttribute("aria-current", "page");
  await expectNoHorizontalOverflow(page);
});

test("credits lists sources", async ({page}) => {
  await page.goto("/credits");
  await expect(page.getByRole("heading", {level: 1, name: "المصادر والشكر"})).toBeVisible();
  await expect(page.getByRole("heading", {name: "الوقف والابتداء"})).toBeVisible();
  await expect(page.getByRole("contentinfo").getByRole("link", {name: "تدريب"})).toHaveAttribute("href", "/waqf-practice");
});

