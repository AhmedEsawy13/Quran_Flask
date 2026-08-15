import type { ReactNode, SVGProps } from "react";

export type AtharIconName =
  | "book"
  | "book-open"
  | "crosshair"
  | "eye"
  | "eye-off"
  | "headphones"
  | "layers"
  | "message"
  | "mouse-pointer"
  | "play"
  | "scan"
  | "settings"
  | "sparkles"
  | "zoom-in"
  | "zoom-out";

const ATHAR_ICON_PATHS: Record<AtharIconName, ReactNode> = {
  book: <><path d="M4 3.5h5a3 3 0 0 1 3 3v14a3 3 0 0 0-3-3H4z" /><path d="M20 3.5h-5a3 3 0 0 0-3 3v14a3 3 0 0 1 3-3h5z" /></>,
  "book-open": <><path d="M2 5.5h6a4 4 0 0 1 4 4v10a4 4 0 0 0-4-4H2z" /><path d="M22 5.5h-6a4 4 0 0 0-4 4v10a4 4 0 0 1 4-4h6z" /></>,
  crosshair: <><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></>,
  eye: <><path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" /><circle cx="12" cy="12" r="2.5" /></>,
  "eye-off": <><path d="m3 3 18 18" /><path d="M10.6 6.2A9.7 9.7 0 0 1 12 6c6.1 0 9.5 6 9.5 6a16 16 0 0 1-2.2 3" /><path d="M6.6 6.7C4 8.5 2.5 12 2.5 12s3.4 6 9.5 6a9.6 9.6 0 0 0 3.3-.6" /><path d="M9.9 9.8a3 3 0 0 0 4.3 4.3" /></>,
  headphones: <><path d="M4 14v-2a8 8 0 0 1 16 0v2" /><path d="M4 14a2 2 0 0 1 2-2h1v7H6a2 2 0 0 1-2-2zM20 14a2 2 0 0 0-2-2h-1v7h1a2 2 0 0 0 2-2z" /></>,
  layers: <><path d="m12 3-9 5 9 5 9-5z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></>,
  message: <path d="M4 6.5h16v10H8.2L4 20z" />,
  "mouse-pointer": <><path d="m5 3 6.8 16 2.2-6 6-2.2z" /><path d="m14 14 4 4" /></>,
  play: <path d="M8 5.5v13l11-6.5z" />,
  scan: <><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3" /><path d="M8 12h8" /></>,
  settings: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2.2" /><circle cx="8" cy="17" r="2.2" /></>,
  sparkles: <><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2z" /><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7zM5 14l.6 1.9 1.9.6-1.9.6L5 19l-.6-1.9-1.9-.6 1.9-.6z" /></>,
  "zoom-in": <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5M10.5 7.5v6M7.5 10.5h6" /></>,
  "zoom-out": <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5M7.5 10.5h6" /></>,
};

export function AtharIcon({name, ...props}: SVGProps<SVGSVGElement> & {name: AtharIconName}) {

  return (
    <svg
      aria-hidden="true"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      {...props}
    >
      {ATHAR_ICON_PATHS[name]}
    </svg>
  );
}
