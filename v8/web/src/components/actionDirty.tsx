import { createContext, useContext, useEffect } from "react";

/** S12 sweep #12: an Actions drawer body tells its host it holds unsaved edits, so closing asks first. */
export const ActionDirtyContext = createContext<((dirty: boolean) => void) | null>(null);

export function useActionDirty(dirty: boolean): void {
  const set = useContext(ActionDirtyContext);
  useEffect(() => {
    set?.(dirty);
    return () => set?.(false);
  }, [dirty, set]);
}
