import { useEffect, useState } from "react";
import { api } from "../api/client";
import { usePolling } from "./usePolling";

// Background count of in-flight builds, for the nav badge. The sidebar is mounted
// on every page, so this polls gently and always -- a build you kicked off on the
// Documents page (or another tab) surfaces in the nav without visiting Jobs. Fails
// silent: a transient error, or a 401 before login, just leaves the last count.
export function useRunningJobsCount(): number {
  const [count, setCount] = useState(0);
  const load = async () => {
    try {
      const jobs = await api.listJobs();
      setCount(jobs.filter((j) => j.status === "building").length);
    } catch { /* keep the last known count */ }
  };
  useEffect(() => { load(); }, []);
  usePolling(load, 5000, true);
  return count;
}
