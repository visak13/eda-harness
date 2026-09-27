import { PageHeader } from "../components/PageHeader";

// Route destinations live in their own files; src/routes.tsx imports the main flow directly and loads every
// other page lazily (S22 route split), so this barrel re-exports nothing — a re-export here would pull a
// lazy page back into the entry bundle.

export function NotFoundPage(): React.JSX.Element {
  return (
    <>
      <PageHeader title="Not found" subtitle="No such page on the board." />
    </>
  );
}
