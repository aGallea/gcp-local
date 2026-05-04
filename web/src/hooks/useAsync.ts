import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncStatus = "idle" | "loading" | "success" | "error";

export interface AsyncState<T> {
  status: AsyncStatus;
  data: T | null;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<{ status: AsyncStatus; data: T | null; error: Error | null }>(
    { status: "idle", data: null, error: null },
  );
  const fnRef = useRef(fn);

  useEffect(() => {
    fnRef.current = fn;
  });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, status: "loading", error: null }));
    try {
      const data = await fnRef.current();
      setState({ status: "success", data, error: null });
    } catch (e) {
      setState({
        status: "error",
        data: null,
        error: e instanceof Error ? e : new Error(String(e)),
      });
    }
  }, []);

  useEffect(() => {
    // run() is async and only mutates state inside its own promise chain, so
    // there is no synchronous setState happening in this effect body — but the
    // react-hooks/set-state-in-effect rule cannot see through the async call.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, refresh: run };
}
