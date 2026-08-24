"use client";

import { useEffect, useState } from "react";

export function useObjectUrl(blob: Blob | null): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    const next = blob ? URL.createObjectURL(blob) : null;
    // Publishing the external resource is the synchronization this effect owns.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUrl(next);
    return () => {
      if (next) URL.revokeObjectURL(next);
    };
  }, [blob]);

  return url;
}
