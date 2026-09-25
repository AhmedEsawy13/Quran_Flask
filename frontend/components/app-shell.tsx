"use client";

import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect, useRef} from "react";
import {ThemeToggle} from "@/components/theme-toggle";
import {AtharMark, DoorIcon, type DoorKey} from "@/components/ui/door-icon";
import {cn} from "@/lib/cn";

const navItems: Array<{key: DoorKey; label: string; href: string}> = [
  {key: "read", label: "المصحف", href: "/read"},
  {key: "memorize", label: "تثبيت", href: "/memorize"},
  {key: "waqf", label: "مُكْث", href: "/waqf"},
  {key: "practice", label: "تدريب", href: "/waqf-practice"},
];

function isActivePath(pathname: string, item: (typeof navItems)[number]) {
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function AppShell({children}: Readonly<{children: React.ReactNode}>) {
  const pathname = usePathname();
  const previousPathname = useRef(pathname);
  const isStudio = pathname === "/memorize";
  const isReader = pathname === "/read";

  useEffect(() => {
    if (previousPathname.current === pathname) return;
    previousPathname.current = pathname;
    window.scrollTo({top: 0, left: 0, behavior: "instant"});
  }, [pathname]);

  useEffect(() => {
    document.documentElement.classList.toggle("is-studio", isStudio);
    return () => document.documentElement.classList.remove("is-studio");
  }, [isStudio]);

  return (
    <>
      <a
        className="fixed start-4 top-2 z-[100] -translate-y-20 rounded-xl bg-athar-surface px-4 py-2 text-athar-ink shadow-athar-sm transition-transform focus:translate-y-0"
        href="#athar-main"
      >
        تجاوز إلى المحتوى
      </a>

      <header className="sticky top-0 z-50 border-b border-athar-line-soft bg-[var(--bar-background)] backdrop-blur-xl backdrop-saturate-150">
        <div className="mx-auto flex min-h-[var(--bar-height)] w-full max-w-[1180px] items-center gap-3 px-3 sm:px-5">
          <Link
            className="group inline-flex items-center gap-2.5 whitespace-nowrap rounded-xl no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-athar-accent"
            href="/"
            aria-label="أثَر — الصفحة الرئيسية"
          >
            <AtharMark className="transition-transform group-hover:-rotate-6" />
            <span className="grid leading-none">
              <span className="font-athar-display text-[1.35rem] text-athar-ink">أثَر</span>
              <span className="mt-0.5 hidden text-[0.66rem] text-athar-ink-faint sm:block">مع القرآن</span>
            </span>
          </Link>

          <nav
            className="ms-auto hidden items-center gap-0.5 rounded-full border border-athar-line-soft bg-[color-mix(in_srgb,var(--athar-surface)_70%,transparent)] p-1 md:flex"
            aria-label="التنقل الرئيسي"
          >
            {navItems.map((item) => {
              const active = isActivePath(pathname, item);
              return (
                <Link
                  className={cn(
                    "inline-flex min-h-9 items-center gap-1.5 rounded-full px-3.5 text-sm font-semibold text-athar-ink-soft no-underline transition-colors hover:bg-athar-line-soft hover:text-athar-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent",
                    active && "bg-athar-accent text-athar-on-accent shadow-sm hover:bg-athar-accent hover:text-athar-on-accent",
                  )}
                  href={item.href}
                  key={item.key}
                  aria-current={active ? "page" : undefined}
                >
                  <DoorIcon name={item.key} className="size-[18px]" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="ms-auto md:ms-0">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className={cn(
        isStudio || isReader
          ? "h-[calc(100dvh-var(--bar-height))] overflow-hidden"
          : "min-h-dvh pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0",
      )}>{children}</div>

      <nav
        className="fixed inset-x-0 bottom-0 z-50 grid grid-cols-4 gap-1 border-t border-athar-line-soft bg-[var(--bar-background)] px-2 pt-1.5 pb-[max(.45rem,env(safe-area-inset-bottom))] shadow-[var(--athar-nav-shadow)] backdrop-blur-xl backdrop-saturate-150 md:hidden"
        aria-label="أبواب التطبيق"
      >
        {navItems.map((item) => {
          const active = isActivePath(pathname, item);
          return (
            <Link
              className={cn(
                "group flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl text-[0.7rem] font-semibold text-athar-ink-faint no-underline transition-colors focus-visible:outline-2 focus-visible:outline-athar-accent",
                active && "text-athar-accent",
              )}
              href={item.href}
              key={item.key}
              aria-current={active ? "page" : undefined}
            >
              <span className={cn(
                "grid h-7 w-14 place-items-center rounded-full transition-colors",
                active ? "bg-athar-accent/14" : "group-hover:bg-athar-line-soft",
              )}>
                <DoorIcon name={item.key} />
              </span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
