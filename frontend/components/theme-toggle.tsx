"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "sepia" | "dark";

const themes: Theme[] = ["light", "sepia", "dark"];
const labels: Record<Theme, string> = {
  light: "الوضع الفاتح — اضغط للتبديل",
  sepia: "الوضع الورقي — اضغط للتبديل",
  dark: "الوضع الليلي — اضغط للتبديل",
};

function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && themes.includes(value as Theme);
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme === "dark" ? "dark" : "light";
}

function ThemeGlyph({theme}: {theme: Theme}) {
  if (theme === "dark") {
    return <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />;
  }
  if (theme === "sepia") {
    return <><path d="M6 3.5h9l3 3v14H6z" /><path d="M15 3.5v3h3M9 11h6M9 14.5h6M9 18h4" /></>;
  }
  return <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" /></>;
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    // The inline bootstrap in layout.tsx already applied the saved or OS theme.
    const frame = window.requestAnimationFrame(() => {
      const current = document.documentElement.dataset.theme;
      setTheme(isTheme(current) ? current : "light");
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  function cycleTheme() {
    const next = themes[(themes.indexOf(theme) + 1) % themes.length];
    setTheme(next);
    applyTheme(next);
    try {
      window.localStorage.setItem("athar-theme", next);
    } catch {
      /* private mode: the choice lasts for this page only */
    }
  }

  return (
    <button
      className="grid size-10 shrink-0 cursor-pointer place-items-center rounded-full border border-athar-line bg-athar-surface text-athar-ink-soft shadow-sm transition-colors hover:border-athar-accent hover:text-athar-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent"
      type="button"
      onClick={cycleTheme}
      aria-label={labels[theme]}
      title={labels[theme]}
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[18px] fill-none stroke-current stroke-[1.7] [stroke-linecap:round] [stroke-linejoin:round]">
        <ThemeGlyph theme={theme} />
      </svg>
    </button>
  );
}
