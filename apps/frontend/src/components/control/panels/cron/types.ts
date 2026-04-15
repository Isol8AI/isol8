// apps/frontend/src/components/control/panels/cron/types.ts

export type CronScheduleKind = "at" | "every" | "cron";

export type CronSchedule =
  | { kind: "at"; at: string }
  | { kind: "every"; everyMs: number; anchorMs?: number }
  | { kind: "cron"; expr: string; tz?: string; staggerMs?: number };

export type CronSessionTarget = "main" | "isolated" | "current" | `session:${string}`;
export type CronWakeMode = "next-heartbeat" | "now";
export type CronDeliveryMode = "none" | "announce" | "webhook";
export type CronRunStatus = "ok" | "error" | "skipped";
export type CronDeliveryStatus = "delivered" | "not-delivered" | "unknown" | "not-requested";
export type CronFailoverReason =
  | "auth"
  | "auth_permanent"
  | "format"
  | "rate_limit"
  | "overloaded"
  | "billing"
  | "timeout"
  | "model_not_found"
  | "session_expired"
  | "unknown";

export interface CronFailureDestination {
  channel?: string;
  to?: string;
  accountId?: string;
  mode?: "announce" | "webhook";
}

export interface CronDelivery {
  mode: CronDeliveryMode;
  channel?: string;
  to?: string;
  threadId?: string | number;
  accountId?: string;
  bestEffort?: boolean;
  failureDestination?: CronFailureDestination;
}

export interface CronFailureAlert {
  after?: number;
  channel?: string;
  to?: string;
  cooldownMs?: number;
  mode?: "announce" | "webhook";
  accountId?: string;
}

export interface CronAgentTurnPayload {
  kind: "agentTurn";
  message: string;
  model?: string;
  fallbacks?: string[];
  thinking?: string;
  timeoutSeconds?: number;
  lightContext?: boolean;
  toolsAllow?: string[];
  allowUnsafeExternalContent?: boolean;
}

export interface CronSystemEventPayload {
  kind: "systemEvent";
  text: string;
}

export type CronPayload = CronAgentTurnPayload | CronSystemEventPayload;

export interface CronJobState {
  nextRunAtMs?: number;
  runningAtMs?: number;
  lastRunAtMs?: number;
  lastRunStatus?: CronRunStatus;
  lastError?: string;
  lastErrorReason?: CronFailoverReason;
  lastDurationMs?: number;
  consecutiveErrors?: number;
  lastFailureAlertAtMs?: number;
  scheduleErrorCount?: number;
  lastDeliveryStatus?: CronDeliveryStatus;
  lastDeliveryError?: string;
  lastDelivered?: boolean;
}

export interface CronJob {
  id: string;
  agentId?: string;
  sessionKey?: string;
  name: string;
  description?: string;
  enabled: boolean;
  deleteAfterRun?: boolean;
  createdAtMs: number;
  updatedAtMs: number;
  schedule: CronSchedule;
  sessionTarget: CronSessionTarget;
  wakeMode: CronWakeMode;
  payload: CronPayload;
  delivery?: CronDelivery;
  failureAlert?: CronFailureAlert | false;
  state: CronJobState;
}

export interface CronUsageSummary {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
}

export interface CronRunEntry {
  jobId: string;
  jobName?: string;
  triggeredAtMs: number;
  completedAtMs?: number;
  status: CronRunStatus;
  error?: string;
  summary?: string;
  runAtMs?: number;
  durationMs?: number;
  nextRunAtMs?: number;
  delivered?: boolean;
  deliveryStatus?: CronDeliveryStatus;
  deliveryError?: string;
  sessionId?: string;
  sessionKey?: string;
  model?: string;
  provider?: string;
  usage?: CronUsageSummary;
}

export interface CronListResponse {
  jobs?: CronJob[];
  total?: number;
  hasMore?: boolean;
}

export interface CronRunsResponse {
  entries?: CronRunEntry[];
  total?: number;
  hasMore?: boolean;
}

export type CronJobPatch = Partial<
  Omit<CronJob, "id" | "createdAtMs" | "state" | "payload">
> & {
  payload?:
    | ({ kind: "agentTurn" } & Partial<Omit<CronAgentTurnPayload, "kind" | "toolsAllow">> & {
          toolsAllow?: string[] | null;
        })
    | ({ kind: "systemEvent" } & Partial<Omit<CronSystemEventPayload, "kind">>);
  delivery?: Partial<CronDelivery>;
  state?: Partial<CronJobState>;
};
