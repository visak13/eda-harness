import { PageHeader, Placeholder } from "../components/PageHeader";

// Route destinations. Real pages live in their own files and are re-exported here (the barrel
// main.tsx imports). G3a owns Epics/Epic/Ticket/Doc/Library; G2 owns Decisions; G3b owns Seats.

export { EpicsPage } from "./Epics";
export { EpicPage } from "./Epic";
export { TicketPage } from "./Ticket";
export { DocPage } from "./Doc";
export { LibraryPage } from "./Library";

// DecisionsPage is G2's, now landed (pages/Decisions.tsx).
export { DecisionsPage } from "./Decisions";

export function SeatsPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Seats" subtitle="Who is alive, and what each shell is doing." />
      <Placeholder story="G3b" />
    </>
  );
}

export function NotFoundPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Not found" subtitle="No such page on the board." />
    </>
  );
}
