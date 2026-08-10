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
      className="theme-toggle"
      type="button"
      onClick={cycleTheme}
      aria-label={labels[theme]}
      title={labels[theme]}
    >
      <span aria-hidden="true">{theme === "dark" ? "☾" : theme === "sepia" ? "◐" : "☼"}</span>
    </button>
  );
}
