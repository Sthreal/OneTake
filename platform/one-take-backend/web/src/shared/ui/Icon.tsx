export type IconName =
  | "folder"
  | "plus"
  | "chevron"
  | "check"
  | "edit"
  | "image"
  | "scan"
  | "text"
  | "quality"
  | "audio"
  | "captions"
  | "film"
  | "video"
  | "lock"
  | "arrow"
  | "agent"
  | "settings"
  | "more"
  | "refresh"
  | "play"
  | "search"
  | "download"
  | "eye"
  | "alert"
  | "x";

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 18, className }: IconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };

  switch (name) {
    case "folder":
      return <svg {...common}><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /></svg>;
    case "plus":
      return <svg {...common}><path d="M5 12h14M12 5v14" /></svg>;
    case "chevron":
      return <svg {...common}><path d="m6 9 6 6 6-6" /></svg>;
    case "check":
      return <svg {...common}><path d="m5 12 4 4L19 6" /></svg>;
    case "edit":
      return <svg {...common}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></svg>;
    case "image":
      return <svg {...common}><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="9" r="1.5" /><path d="m5 17 4.5-4.5 3 3 2-2L19 18" /></svg>;
    case "scan":
      return <svg {...common}><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M7 12h10" /></svg>;
    case "text":
      return <svg {...common}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v5h6M8 13h8M8 17h6" /></svg>;
    case "quality":
      return <svg {...common}><path d="m9 12 2 2 4-4" /><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /></svg>;
    case "audio":
      return <svg {...common}><path d="M2 10v3M6 6v11M10 3v18M14 8v7M18 5v14M22 10v3" /></svg>;
    case "captions":
      return <svg {...common}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 11h3M14 11h3M7 15h5" /></svg>;
    case "film":
      return <svg {...common}><path d="M20.2 6 3 11l-.9-2.4a2 2 0 0 1 1.2-2.5l12.4-4.5a2 2 0 0 1 2.5 1.2Z" /><path d="m6.2 5.3 3.1 3.9M12.4 3.1 15.5 7M18.6.9l3.1 3.9" /><path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>;
    case "video":
      return <svg {...common}><path d="m16 13 5 3V8l-5 3" /><rect x="2" y="6" width="14" height="12" rx="2" /></svg>;
    case "lock":
      return <svg {...common}><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>;
    case "arrow":
      return <svg {...common}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
    case "agent":
      return <svg {...common}><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" /><path d="M8 9h8M8 13h5" /></svg>;
    case "settings":
      return <svg {...common}><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></svg>;
    case "more":
      return <svg {...common}><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" /></svg>;
    case "refresh":
      return <svg {...common}><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 9a7 7 0 0 1 11.6-1L20 12M4 12l2.3 4a7 7 0 0 0 11.6-1" /></svg>;
    case "play":
      return <svg {...common}><path d="m7 4 13 8-13 8V4Z" /></svg>;
    case "search":
      return <svg {...common}><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>;
    case "download":
      return <svg {...common}><path d="M12 3v12M7 10l5 5 5-5M4 20h16" /></svg>;
    case "eye":
      return <svg {...common}><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /></svg>;
    case "alert":
      return <svg {...common}><path d="M12 3 2.5 20h19Z" /><path d="M12 9v5M12 17h.01" /></svg>;
    case "x":
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18" /></svg>;
  }
}
