import { stopBoard } from "./board";

export default async function globalTeardown(): Promise<void> {
  stopBoard();
}
