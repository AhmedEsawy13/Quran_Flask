"use client";

import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect, useRef} from "react";
import {ThemeToggle} from "@/components/theme-toggle";
import {cn} from "@/lib/cn";

type NavKey = "read" | "memorize" | "waqf" | "practice";

const navItems: Array<{
  key: NavKey;
  label: string;
  href: string;
  external?: boolean;
}> = [
  {key: "read", label: "المصحف", href: "/read"},
  {key: "memorize", label: "تثبيت", href: "/memorize"},
  {key: "waqf", label: "مُكْث", href: "/waqf"},
  {key: "practice", label: "تدريب", href: "/waqf-practice"},
];

function NavGlyph({name}: {name: NavKey}) {
  if (name === "read") {
    return <path d="M4 5.5c2.9-.8 5.1-.25 8 1.5 2.9-1.75 5.1-2.3 8-1.5v13c-2.9-.8-5.1-.25-8 1.5-2.9-1.75-5.1-2.3-8-1.5v-13Zm8 1.5v13" />;
  }
  if (name === "memorize") {
    return <path d="M6.2 7.2A7.5 7.5 0 0 1 19 10h2.2L18 13.2 14.8 10H17a5.5 5.5 0 0 0-9.35-1.55M17.8 16.8A7.5 7.5 0 0 1 5 14H2.8L6 10.8 9.2 14H7a5.5 5.5 0 0 0 9.35 1.55" />;
  }
  if (name === "waqf") {
    return <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-2.3-12v6m4.6-6v6" />;
  }
  return <path d="M12 3v3m0 12v3M3 12h3m12 0h3m-6.2-4.8-5.6 9.6m0-9.6 5.6 9.6M12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6Z" />;
}

function NavIcon({name}: {name: NavKey}) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 fill-none stroke-current stroke-[1.7] [stroke-linecap:round] [stroke-linejoin:round]">
      <NavGlyph name={name} />
    </svg>
  );
}

function isActivePath(pathname: string, item: (typeof navItems)[number]) {
  return !item.external && (pathname === item.href || pathname.startsWith(`${item.href}/`));
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

      <header className="sticky top-0 z-50 border-b border-athar-line-soft bg-[var(--bar-background)] backdrop-blur-xl">
        <div className="mx-auto flex min-h-[var(--bar-height)] w-full max-w-[1180px] items-center gap-3 px-3 sm:px-5">
          <Link className="inline-flex items-baseline gap-2 whitespace-nowrap no-underline" href="/" aria-label="أثَر — الصفحة الرئيسية">
            <span className="font-athar-display text-2xl leading-none text-athar-accent">أثَر</span>
            <span className="hidden text-xs text-athar-ink-faint sm:inline">مع القرآن</span>
          </Link>

          <nav className="ms-auto hidden items-center gap-1 md:flex" aria-label="التنقل الرئيسي">
            {navItems.map((item) => {
              const active = isActivePath(pathname, item);
              const className = cn(
                "inline-flex min-h-10 items-center gap-2 rounded-xl px-3 text-sm text-athar-ink-soft no-underline transition-colors hover:bg-athar-line-soft hover:text-athar-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent",
                active && "bg-athar-accent text-athar-on-accent shadow-athar-sm hover:bg-athar-accent hover:text-athar-on-accent",
              );
              const content = <><NavIcon name={item.key} /><span>{item.label}</span></>;
              return item.external ? (
                <a className={className} href={item.href} key={item.key}>{content}</a>
              ) : (
                <Link className={className} href={item.href} key={item.key} aria-current={active ? "page" : undefined}>{content}</Link>
              );
            })}
          </nav>

          <ThemeToggle />
        </div>
      </header>

      <div className={cn(
        isStudio || isReader
          ? "h-[calc(100dvh-var(--bar-height))] overflow-hidden"
          : "min-h-dvh pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0",
      )}>{children}</div>

      <nav
        className="fixed inset-x-0 bottom-0 z-50 grid grid-cols-4 border-t border-athar-line bg-[var(--bar-background)] px-2 pt-1.5 pb-[max(.4rem,env(safe-area-inset-bottom))] shadow-[var(--athar-nav-shadow)] backdrop-blur-xl md:hidden"
        aria-label="التنقل الرئيسي"
      >
        {navItems.map((item) => {
          const active = isActivePath(pathname, item);
          const className = cn(
            "flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl text-[0.68rem] text-athar-ink-faint no-underline transition-colors focus-visible:outline-2 focus-visible:outline-athar-accent",
            active && "bg-athar-accent/10 text-athar-accent",
          );
          const content = <><NavIcon name={item.key} /><span>{item.label}</span></>;
          return item.external ? (
            <a className={className} href={item.href} key={item.key}>{content}</a>
          ) : (
            <Link className={className} href={item.href} key={item.key} aria-current={active ? "page" : undefined}>{content}</Link>
          );
        })}
      </nav>
    </>
  );
}
