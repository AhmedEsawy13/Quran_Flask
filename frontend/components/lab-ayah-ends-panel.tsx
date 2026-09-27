"use client";

import {useEffect, useMemo, useState} from "react";
import {getJson, type Surah} from "@/lib/api";
import {arabicCount, toArabicDigits} from "@/lib/mushaf";
import {isNegativeGrade} from "@/lib/waqf";
import {HIT_PAGE, type AyahEndsPayload} from "@/lib/waqf-lab";
import {HitList, HitRow, ToneChip, ToolBlurb} from "@/components/waqf-lab-hit";
import {SegmentedControl, StatusState} from "@/components/ui/primitives";

type Filter = "all" | "reciters" | "imams" | "mushafs" | "three";

/**
 * Ayah ends are stops by default (الوقف على رؤوس الآي سنة). These are the
 * ones a witness says to join to the next ayah — the reciters who did, the
 * imams who ruled «لا», the mushafs that print «لا».
 */
export function LabAyahEndsPanel({surahs}: {surahs: Surah[]}) {
  const [data, setData] = useState<AyahEndsPayload | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("reciters");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    getJson<AyahEndsPayload>("/backend-api/waqf-research/ayah-ends")
      .then(setData)
      .catch(() => setError("تعذّر تحميل رؤوس الآي."));
  }, []);

  const items = useMemo(() => {
    const all = data?.items || [];
    if (filter === "reciters") return all.filter((item) => item.connect.reciters);
    if (filter === "imams") return all.filter((item) => item.connect.imams);
    if (filter === "mushafs") return all.filter((item) => item.connect.mushafs);
    if (filter === "three") return all.filter((item) => item.witnesses === 3);
    return all;
  }, [data, filter]);

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!data) return <StatusState tone="loading">جارٍ فحص رؤوس الآي في تلاوات القرّاء…</StatusState>;

  return (
    <div className="grid gap-3">
      <ToolBlurb
        shortText="الوقف على رؤوس الآي سنّة، ويقف القرّاء على كلها تقريبًا. هذه رؤوسٌ شهد شاهدٌ بوصلها بما بعدها لتعلّق المعنى."
        longText={`القرّاء: وصلها قارئ فعلًا في تلاوته (لا فاصل بين آخر الآية وأول ما بعدها) — من ${arabicCount(data.reciters_total, ["قارئ واحد", "قارئين", "قرّاء", "قارئًا"])}. الأئمة: حكم كتاب من كتب الوقف عليها بـ«لا» أو «قبيح». المصاحف: طبع مصحفٌ عليها «لا».`}
      />
      <SegmentedControl
        variant="pills"
        className="h-auto w-fit flex-wrap"
        label="الشاهد"
        value={filter}
        options={[
          {value: "reciters", label: `وصلها القرّاء ${toArabicDigits(data.counts.reciters)}`},
          {value: "three", label: `الشواهد الثلاثة ${toArabicDigits(data.counts.all_three)}`},
          {value: "imams", label: `نهى الأئمة عن الوقف ${toArabicDigits(data.counts.imams)}`},
          {value: "mushafs", label: `المصاحف «لا» ${toArabicDigits(data.counts.mushafs)}`},
          {value: "all", label: `الكل ${toArabicDigits(data.count)}`},
        ]}
        onChange={(value) => {
          setFilter(value);
          setShown(HIT_PAGE);
        }}
      />
      <HitList
        items={items}
        shown={shown}
        onShowMore={() => setShown((value) => value + HIT_PAGE)}
        renderItem={(item) => (
          <HitRow
            key={`${item.surah}:${item.ayah}`}
            occurrence={item}
            surahName={surahs.find((surah) => surah.number === item.surah)?.name}
            title={item.joined.length ? `وصلها: ${item.joined.join("، ")}` : undefined}
            meta={(
              <>
                <ToneChip tone={item.witnesses === 3 ? "consensus" : "accent"}>
                  {arabicCount(item.witnesses, ["شاهد واحد", "شاهدان", "شواهد", "شاهدًا"])}
                </ToneChip>
              </>
            )}
            flow={(
              <>
                <ToneChip tone={item.connect.reciters ? "solo" : "muted"}>
                  {item.connect.reciters
                    ? `وصلها ${item.joined.length === 1 ? item.joined[0] : `${toArabicDigits(item.connect.reciters)} من ${toArabicDigits(data.reciters_total)}`}`
                    : `وقف القرّاء جميعًا`}
                </ToneChip>
                {item.imams.map((ruling) => (
                  <ToneChip key={`${ruling.imam}-${ruling.grade}`} tone={isNegativeGrade(ruling.grade) ? "solo" : "muted"}>
                    {ruling.imam}: {ruling.grade}
                  </ToneChip>
                ))}
              </>
            )}
          />
        )}
      />
    </div>
  );
}
