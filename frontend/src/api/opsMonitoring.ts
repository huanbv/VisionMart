import { apiClient } from "./client";

// Types mirror monitoring/server.py's response shapes and
// monitoring/collectors/*.py's dataclasses (converted via `to_dict()`).
// Every field that can legitimately be "not measured" is typed as
// nullable rather than assumed present — see the backend collectors for
// why (ENABLE_PERFORMANCE_METRICS off, no ground truth, DB unreachable, etc.).

export interface ServiceHealthStatus {
  ok: boolean;
  reason: string | null;
  latency_ms: number | null;
}

export interface CameraStatus {
  camera_id: string;
  code: string;
  name: string;
  is_online_db: boolean;
  last_seen_at: string | null;
  seconds_since_last_seen: number | null;
  reconnect_count_since_monitoring_start: number;
  fps: number | null;
  dropped_frames_total: number | null;
  avg_pipeline_latency_ms: number | null;
  fps_reason: string | null;
  frozen_frame_detection_available: boolean;
}

export interface CameraHealthSnapshot {
  checked_at: number;
  ai_engine_reachable: boolean;
  ai_engine_reason: string | null;
  performance_metrics_enabled_hint: boolean;
  cameras: CameraStatus[];
  db_reachable: boolean;
  db_reason: string | null;
}

export interface QueueStatus {
  queue_name: string;
  length: number | null;
  reason: string | null;
}

export interface AiPipelineSnapshot {
  checked_at: number;
  ai_engine_reachable: boolean;
  ai_engine_reason: string | null;
  inference_latency_ms: number | null;
  opencv_stage_ms: number | null;
  yolo_bytetrack_stage_ms: number | null;
  pipeline_total_ms: number | null;
  detect_requests_ok_total: number | null;
  detect_requests_error_total: number | null;
  active_tracks: string;
  active_tracks_reason: string;
  queues: QueueStatus[];
}

export interface HostResources {
  cpu_percent: number | null;
  ram_percent: number | null;
  ram_used_gb: number | null;
  ram_total_gb: number | null;
  disk_percent: number | null;
  disk_used_gb: number | null;
  disk_total_gb: number | null;
  gpu_available: boolean;
  gpu_util_percent: number | null;
  gpu_mem_used_mb: number | null;
  gpu_mem_total_mb: number | null;
  reason: string | null;
}

export interface DockerContainerStatus {
  name: string;
  status: string;
  health: string | null;
  cpu_percent: number | null;
  mem_usage_mb: number | null;
  restart_count: number | null;
}

export interface SystemResourceSnapshot {
  checked_at: number;
  host: HostResources;
  docker: { reachable: boolean; reason: string | null; containers: DockerContainerStatus[] };
  celery: { reachable: boolean; reason: string | null; worker_count: number; workers: Record<string, { active: number; reserved: number }> };
  redis: { reachable: boolean; reason: string | null; used_memory_mb: number | null; connected_clients: number | null };
  postgres: { reachable: boolean; reason: string | null; active_connections: number | null };
}

export interface AlertRecord {
  id: number;
  rule_id: string;
  severity: "critical" | "warning" | "info";
  subject: string;
  message: string;
  first_seen: number;
  last_seen: number;
  resolved_at: number | null;
  status: "active" | "resolved";
}

export interface OverviewResponse {
  generated_at: number;
  poller: { last_poll_ts: number | null; poll_interval_seconds: number; last_error: string | null };
  health_score: Partial<HealthScoreResponse>;
  service_health: { backend?: ServiceHealthStatus; ai_engine?: ServiceHealthStatus };
  camera_summary: { total: number; online: number };
  ai_pipeline: Partial<AiPipelineSnapshot>;
  system: Partial<SystemResourceSnapshot>;
  evaluation: Partial<EvaluationStatusResponse>;
  active_alert_count: number;
  active_alerts: AlertRecord[];
}

export interface SessionLifecycleView {
  cart_id: string;
  source: string;
  current_stage: string;
  status: string;
  item_count: number;
  total_amount: string;
  created_at: string | null;
  checkout_requested_at: string | null;
  converted_at: string | null;
  observed_events: { ts: number; stage: string; detail: Record<string, unknown> | null }[];
  observation_note: string;
}

export interface SessionLifecycleResponse {
  checked_at: number;
  reachable: boolean;
  reason: string | null;
  sessions: SessionLifecycleView[];
}

// Mirrors monitoring/health_score.py's HealthScoreResult.to_dict().
export interface HealthScoreResponse {
  score: number;
  status: "Healthy" | "Warning" | "Degraded" | "Critical" | "Offline";
  components: Record<string, string>;
  reasoning: string[];
  generated_at: number;
}

// Mirrors monitoring/collectors/evaluation_health.py's EvaluationStatus.to_dict()
// (also embedded as `evaluation` inside OverviewResponse once the backend
// snapshot has run at least once).
export interface EvaluationStatusResponse {
  reachable: boolean;
  reason: string | null;
  reports_dir: string;
  report_count: number;
  last_report_age_seconds: number | null;
  note?: string;
}

// Mirrors monitoring/collectors/release_info.py's collect_release_info().
export interface ReleaseInfoResponse {
  application_version: string;
  component_versions: Record<string, string>;
  git: { commit: string; commit_short: string; branch: string; dirty: boolean | null };
  build_time_utc: string | null;
  docker_image_tag: string;
  environment: string;
  pinned_runtimes: Record<string, string>;
  runtime: {
    monitoring_python_version: string;
    os: string;
    os_release: string;
    os_version: string;
    machine: string;
    database_version: string;
  };
  honesty_note?: string;
  _source?: string;
  _error?: string;
}

export async function getOverview(): Promise<OverviewResponse> {
  const { data } = await apiClient.get<OverviewResponse>("/ops-monitoring/overview");
  return data;
}

export async function getCameraHealth(): Promise<CameraHealthSnapshot> {
  const { data } = await apiClient.get<CameraHealthSnapshot>("/ops-monitoring/cameras");
  return data;
}

export async function getAiPipelineHealth(): Promise<AiPipelineSnapshot> {
  const { data } = await apiClient.get<AiPipelineSnapshot>("/ops-monitoring/ai-pipeline");
  return data;
}

export async function getSystemResources(): Promise<SystemResourceSnapshot> {
  const { data } = await apiClient.get<SystemResourceSnapshot>("/ops-monitoring/system");
  return data;
}

export async function getActiveAlerts(): Promise<{ active: AlertRecord[] }> {
  const { data } = await apiClient.get<{ active: AlertRecord[] }>("/ops-monitoring/alerts");
  return data;
}

export async function getAlertHistory(limit = 100): Promise<{ alerts: AlertRecord[] }> {
  const { data } = await apiClient.get<{ alerts: AlertRecord[] }>("/ops-monitoring/alerts/history", {
    params: { limit },
  });
  return data;
}

export async function getSessionLifecycle(
  sinceHours = 24,
  limit = 200,
): Promise<SessionLifecycleResponse> {
  const { data } = await apiClient.get<SessionLifecycleResponse>("/ops-monitoring/sessions", {
    params: { since_hours: sinceHours, limit },
  });
  return data;
}

export async function getHealthScore(): Promise<HealthScoreResponse> {
  const { data } = await apiClient.get<HealthScoreResponse>("/ops-monitoring/health-score");
  return data;
}

export async function getEvaluationStatus(): Promise<EvaluationStatusResponse> {
  const { data } = await apiClient.get<EvaluationStatusResponse>("/ops-monitoring/evaluation");
  return data;
}

export async function getReleaseInfo(): Promise<ReleaseInfoResponse> {
  const { data } = await apiClient.get<ReleaseInfoResponse>("/ops-monitoring/release-info");
  return data;
}

// Part 5 (Production Readiness Report) — endpoint stub already proxied by
// the backend (`/ops-monitoring/readiness`); response shape is finalized
// once monitoring/readiness.py lands. Typed loosely for now and narrowed
// when the readiness UI is built.
export interface ReadinessCheckItem {
  category: string;
  name: string;
  status: "PASS" | "WARNING" | "FAIL";
  detail: string;
  recommendation: string | null;
}

export interface ReadinessResponse {
  generated_at: number;
  overall_status: "PASS" | "WARNING" | "FAIL";
  checks: ReadinessCheckItem[];
}

export async function getReadiness(): Promise<ReadinessResponse> {
  const { data } = await apiClient.get<ReadinessResponse>("/ops-monitoring/readiness");
  return data;
}
