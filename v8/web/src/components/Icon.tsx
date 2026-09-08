// Minimal 18px line icons (stroke = currentColor, so the active nav item tints its icon
// with --accentink via CSS). Not the final icon set — enough for the shell nav.
const PATHS: Record<string, string> = {
  decisions: "M4 5h16M4 12h16M4 19h10",
  epics: "M4 6h16v12H4zM4 10h16",
  seats: "M6 20v-2a4 4 0 0 1 8 0v2M10 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM17 20v-2a4 4 0 0 0-3-3.8",
  library: "M4 5v14M8 5v14M12 5l5 13M4 5h4M8 5h3",
  find: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-4-4",
};

export function Icon({ name }: { name: keyof typeof PATHS | string }): React.JSX.Element {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] ?? PATHS.decisions} />
    </svg>
  );
}
