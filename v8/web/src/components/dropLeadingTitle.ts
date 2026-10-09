const plain = (s: string): string => s.replace(/<[^>]*>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#0?39;/g, "'").replace(/\s+/g, " ").trim().toLowerCase();

/** Sweep #14: the reader draws the doc title as its H1, so a body that opens with the same title as an H1/H2 shows it twice. */
export function dropLeadingTitle(html: string, title: string): string {
  const m = /^\s*<h([12])\b[^>]*>([\s\S]*?)<\/h\1>/i.exec(html);
  if (!m) return html;
  const heading = plain(m[2]);
  const want = plain(title);
  return heading && (heading === want || want.endsWith(heading) || heading.endsWith(want)) ? html.slice(m[0].length) : html;
}

/** The Epic page labels the design link "Design:", so a title that already starts "Design: " must not say it twice. */
export const stripDesignPrefix = (title: string): string => title.replace(/^Design:\s*/i, "");
