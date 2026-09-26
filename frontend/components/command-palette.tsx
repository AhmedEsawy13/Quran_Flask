"use client";

import {useRouter} from "next/navigation";
import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import type {Surah} from "@/lib/api";
import {cn} from "@/lib/cn";
import {toArabicDigits} from "@/lib/mushaf";
import {loadSurahs} from "@/lib/surahs";
import {allTools, labWordHref, toolHref, toolPath, waqfTools, type ToolKey} from "@/lib/nav";
import {arabicWordQuery, parseVerseSearch} from "@/lib/waqf-search";
import {DoorIcon, type DoorKey} from "@/components/ui/door-icon";

type Command = {id: string; icon: DoorKey; title: string; hint: string; href: string};

function typingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

const verseActions: Array<{key: ToolKey; title: string}> = [
  {key: "waqf", title: "ادرس وقفها في مُكْث"},
  {key: "practice", title: "تدرّب على وقفها"},
  {key: "read", title: "اقرأها في المصحف"},
  {key: "memorize", title: "احفظها في تثبيت"},
];

function buildCommands(query: string, surahs: Surah[]): Command[] {
  const trimmed = query.trim();
  if (!trimmed) {
    return allTools.map((tool) => ({
      id: tool.key,
      icon: tool.key,
      title: tool.title,
      hint: tool.description,
      href: toolPath(tool.key),
    }));
  }

  const commands: Command[] = [];
  const verse = parseVerseSearch(trimmed, surahs);
  if (verse && verse.surah >= 1 && verse.surah <= 114) {
    const name = surahs.find((surah) => surah.number === verse.surah)?.name || toArabicDigits(verse.surah);
    const place = `${name} · الآية ${toArabicDigits(verse.ayah)}`;
    verseActions.forEach(({key, title}) => commands.push({
      id: `${key}:${verse.surah}:${verse.ayah}`,
      icon: key,
      title,
      hint: place,
      href: toolHref(key, verse),
    }));
  }

  const word = arabicWordQuery(trimmed);
  if (word && !verse) {
    commands.push({
      id: `lab:${word}`,
      icon: "lab",
      title: `ابحث عن «${word}» في مختبر الوقف`,
      hint: "كل مواضعها في القرآن، وأين يوقف عليها",
      href: labWordHref(word),
    });
  }

  allTools
    .filter((tool) => `${tool.label} ${tool.title} ${tool.verb}`.includes(trimmed))
    .forEach((tool) => commands.push({
      id: tool.key,
      icon: tool.key,
      title: tool.title,
      hint: tool.description,
      href: toolPath(tool.key),
    }));
  return commands;
}

export function CommandPalette({open, onOpenChange}: {open: boolean; onOpenChange: (open: boolean) => void}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [active, setActive] = useState(0);

  const close = useCallback(() => {
    onOpenChange(false);
    setQuery("");
    setActive(0);
  }, [onOpenChange]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      } else if (event.key === "/" && !open && !typingTarget(event.target) && !event.altKey && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        onOpenChange(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    let cancelled = false;
    loadSurahs().then((items) => {
      if (!cancelled) setSurahs(items);
    }).catch(() => undefined);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      cancelled = true;
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  const commands = useMemo(() => buildCommands(query, surahs), [query, surahs]);
  const activeIndex = Math.min(active, Math.max(commands.length - 1, 0));

  const go = (command: Command | undefined) => {
    if (!command) return;
    close();
    router.push(command.href);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center bg-[color-mix(in_srgb,var(--athar-ink)_38%,transparent)] px-3 pt-[min(14vh,120px)] backdrop-blur-[3px]" onMouseDown={(event) => {
      if (event.target === event.currentTarget) close();
    }}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="انتقل إلى آية أو أداة"
        className="w-full max-w-[600px] overflow-hidden rounded-athar-lg border border-athar-line bg-athar-surface shadow-athar-lg"
      >
        <div className="flex items-center gap-3 border-b border-athar-line px-4">
          <DoorIcon name="search" className="size-5 shrink-0 text-athar-ink-faint" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls="athar-palette-list"
            aria-activedescendant={commands.length ? `athar-palette-${activeIndex}` : undefined}
            className="min-h-14 flex-1 bg-transparent text-base text-athar-ink outline-none placeholder:text-athar-ink-faint"
            placeholder="آية (٢:٢٥٥ · الكهف ١٠) أو كلمة أو أداة"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((activeIndex + 1) % Math.max(commands.length, 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive(activeIndex <= 0 ? commands.length - 1 : activeIndex - 1);
              } else if (event.key === "Enter") {
                event.preventDefault();
                go(commands[activeIndex]);
              } else if (event.key === "Escape") {
                event.preventDefault();
                close();
              }
            }}
          />
          <kbd className="hidden rounded-md border border-athar-line px-1.5 py-0.5 font-athar-ui text-[0.7rem] text-athar-ink-faint sm:inline">Esc</kbd>
        </div>
        <ul id="athar-palette-list" role="listbox" aria-label="النتائج" className="m-0 max-h-[min(60vh,420px)] list-none overflow-y-auto p-2">
          {!query.trim() ? (
            <li role="presentation" className="px-3 pt-1 pb-2 text-[0.72rem] font-bold text-athar-gold">الأدوات</li>
          ) : null}
          {commands.map((command, index) => (
            <li key={command.id} role="presentation">
              <button
                type="button"
                role="option"
                id={`athar-palette-${index}`}
                aria-selected={index === activeIndex}
                onMouseEnter={() => setActive(index)}
                onClick={() => go(command)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start transition-colors",
                  index === activeIndex ? "bg-athar-accent/10" : "hover:bg-athar-line-soft",
                )}
              >
                <span className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-[10px]",
                  waqfTools.some((tool) => tool.key === command.icon)
                    ? "bg-athar-accent/12 text-athar-accent"
                    : "bg-athar-line-soft text-athar-ink-soft",
                )}>
                  <DoorIcon name={command.icon} className="size-[18px]" />
                </span>
                <span className="grid min-w-0 flex-1">
                  <span className="truncate font-bold text-athar-ink">{command.title}</span>
                  <span className="truncate text-[0.78rem] text-athar-ink-faint">{command.hint}</span>
                </span>
                {index === activeIndex ? <span aria-hidden="true" className="text-athar-accent">←</span> : null}
              </button>
            </li>
          ))}
          {!commands.length ? (
            <li role="presentation" className="px-3 py-6 text-center text-sm text-athar-ink-faint">
              لم نتعرّف على هذا — جرّب «٢:٢٥٥» أو «البقرة ٢٥٥» أو كلمة من القرآن.
            </li>
          ) : null}
        </ul>
        <p className="m-0 flex flex-wrap gap-x-4 gap-y-1 border-t border-athar-line-soft bg-athar-canvas px-4 py-2 text-[0.72rem] text-athar-ink-faint">
          <span><kbd className="font-athar-ui">↑↓</kbd> للتنقل</span>
          <span><kbd className="font-athar-ui">Enter</kbd> للفتح</span>
          <span>افتحه من أي صفحة بـ <kbd className="font-athar-ui">/</kbd> أو <kbd className="font-athar-ui">Ctrl K</kbd></span>
        </p>
      </div>
    </div>
  );
}
