// dashboard/src/components/useLoad.js — a small React hook that loads data from the API.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

/**
 * Load `path` when the component appears (and every `refreshSeconds`, if given).
 * Out: { data, error, reload } — data is null until the first answer arrives.
 */
export function useLoad(path, refreshSeconds) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    try {
      setData(await api("GET", path));
      setError(null);
    } catch (problem) {
      setError(problem.message);
    }
  }, [path]);

  useEffect(() => {
    reload();
    if (!refreshSeconds) return undefined;
    const timer = setInterval(reload, refreshSeconds * 1000);
    return () => clearInterval(timer);
  }, [reload, refreshSeconds]);

  return { data, error, reload };
}
