import { useParams } from "react-router";
import { PageHeader, Placeholder } from "../components/PageHeader";

// Route destination stubs (design §4.2 IA). Each renders the shell-measured <h1>; bodies
// arrive in later stories (Decisions/inbox → G2, Epics/Ticket/Doc/Library → G3a, Seats → G3b).

export function DecisionsPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Decisions" subtitle="Sign-offs, questions and gates that need you." />
      <Placeholder story="G2" />
    </>
  );
}

export function EpicsPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Epics" subtitle="Every epic on the board and its pulse." />
      <Placeholder story="G3a" />
    </>
  );
}

export function EpicPage(): React.JSX.Element {
  const { id } = useParams();
  return (
    <>
      <PageHeader title="Epic" subtitle={id} />
      <Placeholder story="G3a" />
    </>
  );
}

export function SeatsPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Seats" subtitle="Who is alive, and what each shell is doing." />
      <Placeholder story="G3b" />
    </>
  );
}

export function TicketPage(): React.JSX.Element {
  const { id } = useParams();
  return (
    <>
      <PageHeader title="Ticket" subtitle={id} />
      <Placeholder story="G3a" />
    </>
  );
}

export function DocPage(): React.JSX.Element {
  const { id } = useParams();
  return (
    <>
      <PageHeader title="Document" subtitle={id} />
      <Placeholder story="G3a" />
    </>
  );
}

export function LibraryPage(): React.JSX.Element {
  const { section } = useParams();
  return (
    <>
      <PageHeader title="Library" subtitle={section ? `${section}` : undefined} />
      <Placeholder story="G3a" />
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
