"use client";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { JobCard } from "./JobCard";
import type { CronJob, CronRunEntry } from "./types";

interface JobListProps {
  jobs: CronJob[];
  expandedJobId: string | null;
  onToggleExpand: (jobId: string) => void;
  onCreate: () => void;
  onEdit: (job: CronJob) => void;
  onPauseResume: (job: CronJob) => void;
  onRunNow: (job: CronJob) => void;
  onDelete: (job: CronJob) => void;
  onSelectRun: (job: CronJob, run: CronRunEntry) => void;
}

export function JobList(props: JobListProps) {
  const { jobs, expandedJobId, onCreate } = props;

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <p className="text-[#8a8578] mb-4">No crons yet</p>
        <Button onClick={onCreate}>
          <Plus className="h-4 w-4 mr-2" /> Create your first cron
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button size="sm" onClick={onCreate}>
          <Plus className="h-4 w-4 mr-2" /> New cron
        </Button>
      </div>
      {jobs.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          expanded={expandedJobId === job.id}
          onToggleExpand={() => props.onToggleExpand(job.id)}
          onEdit={() => props.onEdit(job)}
          onPauseResume={() => props.onPauseResume(job)}
          onRunNow={() => props.onRunNow(job)}
          onDelete={() => props.onDelete(job)}
          onSelectRun={(run) => props.onSelectRun(job, run)}
        />
      ))}
    </div>
  );
}
