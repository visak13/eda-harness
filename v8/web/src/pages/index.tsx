import { PageHeader } from "../components/PageHeader";

// Route destinations. Real pages live in their own files and are re-exported here (the barrel
// main.tsx imports). G3a owns Epics/Epic/Ticket/Doc/Library; G2 owns Decisions; G3b owns Seats.

export { EpicsPage } from "./Epics";
export { EpicPage } from "./Epic";
export { TicketPage } from "./Ticket";
export { DocPage } from "./Doc";
export { LibraryPage } from "./Library";
export { TopicPage } from "./TopicPage";
export { ArtifactPage } from "./Artifact";

// DecisionsPage is G2's, now landed (pages/Decisions.tsx).
export { DecisionsPage } from "./Decisions";

// SeatsPage is G3b's, now landed (pages/Seats.tsx).
export { SeatsPage } from "./Seats";

export function NotFoundPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Not found" subtitle="No such page on the board." />
    </>
  );
}
