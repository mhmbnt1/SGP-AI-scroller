import type { JobDetailOut } from "@focusfeed/contracts";
import { useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { Badge, Button, Card } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useColors } from "@/theme";

const TERMINAL = new Set(["completed", "partial", "needs_user_action", "cancelled", "failed"]);

export function useJob(jobId: string | null, onDone?: (job: JobDetailOut) => void) {
  const [job, setJob] = useState<JobDetailOut | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    let delay = 1000;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await unwrap(api.GET("/api/v1/jobs/{job_id}", { params: { path: { job_id: jobId } } }));
        if (stop) return;
        setJob(j);
        if (TERMINAL.has(j.state)) { doneRef.current?.(j); return; }
        delay = 1500;
      } catch {
        delay = Math.min(delay * 2, 10_000);
      }
      timer = setTimeout(tick, delay);
    };
    void tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [jobId]);
  async function cancel() {
    if (!jobId) return;
    const j = await unwrap(api.POST("/api/v1/jobs/{job_id}/cancel", { params: { path: { job_id: jobId } } }));
    setJob((p) => (p ? { ...p, ...j } : p));
  }
  return { job, cancel };
}

export function JobProgress({ job, onCancel }: { job: JobDetailOut; onCancel?: () => void }) {
  const c = useColors();
  const terminal = TERMINAL.has(job.state);
  return (
    <Card>
      <Text style={{ color: c.text, fontWeight: "700" }}>{job.mode === "search" ? "Searching" : "Collecting"} — {job.state.replace(/_/g, " ")}</Text>
      <View accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: job.progress }} style={{ height: 8, borderRadius: 999, backgroundColor: c.surface2, overflow: "hidden" }}>
        <View style={{ width: `${job.progress}%`, height: "100%", backgroundColor: c.accent }} />
      </View>
      <Text style={{ color: c.muted }}>{job.next_step}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>{Object.entries(job.platform_states).map(([p, s]) => <Badge key={p} kind={s === "available" ? "ok" : s === "pending" ? "default" : "bad"}>{p}: {String(s)}</Badge>)}</View>
      {!terminal && onCancel ? <Button title={job.cancel_requested ? "Cancelling…" : "Cancel"} variant="danger" disabled={job.cancel_requested} onPress={onCancel} /> : null}
    </Card>
  );
}
