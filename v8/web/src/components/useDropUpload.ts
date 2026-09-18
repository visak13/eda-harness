import { useCallback, useState } from "react";
import type { UploadedArtifact } from "../api/types";
import { uploadArtifact } from "../api/endpoints";

// The one drop-to-attach path (promise #19). The composer, the Ticket page's "Linked documents"
// card and the ruling drawer all attach a dropped (or pasted) file the same way: every file goes
// through POST /v1/artifacts/upload against the ticket, each success is reported to the host,
// and a refused upload leaves whatever the host holds intact and surfaces the board's reason.

export interface DropUpload {
  /** A file is being dragged over the target — the host paints its drag-over state. */
  dragOver: boolean;
  /** The last refused upload's reason (the board's hint), else null. */
  error: string | null;
  pending: number;
  retry: () => void;
  clearError: () => void;
  /** Upload each file in turn; `onUploaded` fires per success. Safe to call from a paste too. */
  ingestFiles: (files: FileList | File[]) => Promise<void>;
  /** Spread onto the drop target element. */
  dropProps: {
    onDragOver: (e: React.DragEvent) => void;
    onDragLeave: () => void;
    onDrop: (e: React.DragEvent) => void;
  };
}

export function useDropUpload(ticketId: string, onUploaded: (art: UploadedArtifact, file?: File) => void): DropUpload {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState<File[]>([]);

  const ingestFiles = useCallback(
    async (files: FileList | File[]) => {
      setError(null);
      const list = Array.from(files);
      setPending((n) => n + list.length);
      for (const file of list) {
        try {
          if (file.size > 25 * 1024 * 1024) throw new Error("File exceeds the 25 MB limit");
          onUploaded(await uploadArtifact(file, ticketId), file);
        } catch (err) {
          setFailed((old) => [...old, file]);
          setError(err instanceof Error ? err.message : String(err));
        } finally { setPending((n) => n - 1); }
      }
    },
    [ticketId, onUploaded],
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);
  const onDragLeave = useCallback(() => setDragOver(false), []);
  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files.length) void ingestFiles(e.dataTransfer.files);
    },
    [ingestFiles],
  );

  return { dragOver, error, pending, retry: () => { const files = failed; setFailed([]); void ingestFiles(files); }, clearError: () => { setFailed([]); setError(null); }, ingestFiles, dropProps: { onDragOver, onDragLeave, onDrop } };
}
