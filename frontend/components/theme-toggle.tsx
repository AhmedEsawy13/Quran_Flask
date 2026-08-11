"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "sepia" | "dark";

const themes: Theme[] = ["light", "sepia", "dark"];
const labels: Record<Theme, string> = {
  light: "الوضع الفاتح",
  sepia: "الوضع الورقي",
  dark: "الوضع الليلي",
};

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme === "dark" ? "dark" : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const saved = window.localStorage.getItem("athar-theme") as Theme | null;
    const initial = saved && themes.includes(saved) ? saved : "light";
    const frame = window.requestAnimationFrame(() => {
      setTheme(initial);
      applyTheme(initial);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  function cycleTheme() {
    const next = themes[(themes.indexOf(theme) + 1) % themes.length];
    setTheme(next);
    applyTheme(next);
    window.localStorage.setItem("athar-theme", next);
  }

  return (
    <button
      className="ms-auto grid size-10 shrink-0 place-items-center rounded-full border border-athar-line bg-athar-surface text-athar-ink shadow-sm transition-colors hover:border-athar-accent hover:text-athar-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent md:ms-0"
      type="button"
      onClick={cycleTheme}
      aria-label={labels[theme]}
      title={labels[theme]}
    >
      <span aria-hidden="true">{theme === "dark" ? "☾" : theme === "sepia" ? "◐" : "☼"}</span>
    </button>
  );
}
