import { useCallback, useEffect, useRef, useState } from "react";

/** A callback ref and the element's content width, kept up to date on resize (for SVGs that fill their column). */
export function useElementWidth<T extends HTMLElement>(fallback: number): [(el: T | null) => void, number] {
  const [w, setW] = useState(fallback);
  const ro = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: T | null) => {
    ro.current?.disconnect();
    if (!el) return;
    const measure = () => setW(Math.max(120, Math.floor(el.clientWidth)));
    measure();
    ro.current = new ResizeObserver(measure);
    ro.current.observe(el);
  }, []);
  useEffect(() => () => ro.current?.disconnect(), []);
  return [ref, w];
}
