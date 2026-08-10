import Link from "next/link";
import { legacyUrl } from "@/lib/paths";
import { ThemeToggle } from "@/components/theme-toggle";

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <a className="skip-link" href="#athar-main">
        تجاوز إلى المحتوى
      </a>
      <header className="app-bar">
        <Link className="brand" href="/" aria-label="أثَر — الصفحة الرئيسية">
          <span className="brand-name">أثَر</span>
          <span className="brand-tagline">مع القرآن</span>
        </Link>
        <nav className="main-nav" aria-label="التنقل الرئيسي">
          <Link href="/read">المصحف</Link>
          <a href={legacyUrl("/memorize")}>تثبيت</a>
          <a href={legacyUrl("/waqf")}>مُكْث</a>
          <a href={legacyUrl("/waqf-practice")}>تدريب</a>
        </nav>
        <ThemeToggle />
      </header>
      {children}
    </>
  );
}
