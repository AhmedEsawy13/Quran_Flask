"use client";

import {useRouter} from "next/navigation";
import {useState} from "react";
import {labWordHref, toolHref} from "@/lib/nav";
import {loadSurahs} from "@/lib/surahs";
import {arabicWordQuery, parseVerseSearch} from "@/lib/waqf-search";
import {DoorIcon} from "@/components/ui/door-icon";

/** «٢:٢٥٥» or «الكهف ١٠» opens the ayah in مُكْث; a word opens the lab's word search. */
export function VerseJump() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [hint, setHint] = useState("");

  const submit = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    const surahs = await loadSurahs().catch(() => []);
    const verse = parseVerseSearch(trimmed, surahs);
    if (verse && verse.surah >= 1 && verse.surah <= 114) {
      router.push(toolHref("waqf", verse));
      return;
    }
    const word = arabicWordQuery(trimmed);
    if (word) {
      router.push(labWordHref(word));
      return;
    }
    setHint("اكتب رقم السورة والآية مثل ٢:٢٥٥، أو اسم السورة ورقم الآية، أو كلمة من القرآن.");
  };

  return (
    <form
      className="mt-7 grid max-w-[560px] gap-2"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label htmlFor="verse-jump" className="text-[0.8rem] font-bold text-athar-ink-soft">ادرس وقف أي آية</label>
      <div className="flex items-center gap-2 rounded-2xl border border-athar-line bg-athar-surface p-1.5 shadow-athar-sm transition-colors focus-within:border-athar-accent">
        <DoorIcon name="search" className="ms-2 size-5 shrink-0 text-athar-ink-faint" />
        <input
          id="verse-jump"
          className="min-h-11 min-w-0 flex-1 bg-transparent text-base text-athar-ink outline-none placeholder:text-athar-ink-faint"
          placeholder="٢:٢٥٥ · الكهف ١٠ · أو كلمة"
          value={query}
          aria-describedby={hint ? "verse-jump-hint" : undefined}
          onChange={(event) => {
            setQuery(event.target.value);
            setHint("");
          }}
        />
        <button
          type="submit"
          className="min-h-11 shrink-0 rounded-xl bg-athar-accent px-5 font-bold text-athar-on-accent transition-colors hover:bg-athar-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent"
        >
          افتح
        </button>
      </div>
      {hint ? <p id="verse-jump-hint" className="m-0 text-[0.8rem] text-athar-copper" role="status">{hint}</p> : null}
    </form>
  );
}
