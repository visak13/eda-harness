import { useParams } from "react-router";
import { ContextualWork } from "../components/ContextualWork";
export function RecordsPage(): React.JSX.Element {
  const { id = "" } = useParams();
  return <ContextualWork ticketId={id} dedicated />;
}
