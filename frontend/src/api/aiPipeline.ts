import { apiClient } from "./client";

/**
 * AI pipeline dashboard: browse what the AI actually did, session by
 * session, frame by frame, step by step.
 *
 * This is the *stored history* view — distinct from PipelineTracePage,
 * which re-runs preprocessing on an ad-hoc upload. Here every row already
 * happened on a real camera and was recorded by the ai-engine, so it
 * answers "why did the model do that on Tuesday at 14:03" rather than
 * "what would preprocessing do to this image now".
 */

export interface PipelineSession {
  id: string;
  camera_id: string | null;
  camera_key: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  frame_count: number;
  detection_count: number;
  detector_version: string | null;
  classifier_version: string | null;
  config_snapshot: Record<string, unknown> | null;
}

export interface SessionList {
  items: PipelineSession[];
  total: number;
}

export interface PipelineFrame {
  id: string;
  session_id: string;
  seq: number;
  captured_at: string;
  width: number | null;
  height: number | null;
  storage_prefix: string | null;
  brightness: number | null;
  contrast: number | null;
  blur_score: number | null;
  quality_score: number | null;
  gate_passed: boolean;
  reject_reason: string | null;
  preprocess_ms: number | null;
  detect_ms: number | null;
  classify_ms: number | null;
  ocr_ms: number | null;
  total_ms: number | null;
  steps_applied: Record<string, unknown> | null;
}

export interface FrameList {
  items: PipelineFrame[];
  total: number;
}

export interface Classification {
  sku: string;
  confidence: number;
  runner_up_sku: string | null;
  runner_up_confidence: number | null;
  margin: number | null;
  model_version: string | null;
  inference_ms: number | null;
}

export interface Detection {
  id: string;
  track_id: number | null;
  class_name: string;
  confidence: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  crop_key: string | null;
  combined_confidence: number | null;
}

export interface DetectionWithClassification {
  detection: Detection;
  classification: Classification | null;
}

export interface PipelineLog {
  stage: string;
  level: string;
  message: string;
  elapsed_ms: number | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface FrameDetail {
  frame: PipelineFrame;
  detections: DetectionWithClassification[];
  logs: PipelineLog[];
  previous_frame_id: string | null;
  next_frame_id: string | null;
}

export interface PipelineTrack {
  id: string;
  track_id: number;
  class_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
  frame_count: number;
  resolved_sku: string | null;
  resolved_confidence: number | null;
  resolved_source: string | null;
}

export interface SessionStats {
  frame_count: number;
  rejected_count: number;
  reject_rate: number;
  avg_total_ms: number | null;
  max_total_ms: number | null;
  avg_quality_score: number | null;
  detection_count: number;
  avg_confidence: number | null;
  event_count: number;
}

/** One debug step image (from DEBUG_AI), with a presigned URL to load it. */
export interface FrameStep {
  step: string;
  order: number;
  key: string;
  bytes: number;
  params: Record<string, unknown> | null;
  elapsed_ms: number | null;
  url: string | null;
}

export interface FrameSteps {
  steps: FrameStep[];
  reason?: string;
  manifest?: Record<string, unknown>;
}

export async function listSessions(params: {
  camera_id?: string;
  limit?: number;
  offset?: number;
}): Promise<SessionList> {
  const { data } = await apiClient.get<SessionList>("/ai/pipeline/sessions", {
    params,
  });
  return data;
}

export async function getSessionStats(sessionId: string): Promise<SessionStats> {
  const { data } = await apiClient.get<SessionStats>(
    `/ai/pipeline/sessions/${sessionId}/stats`,
  );
  return data;
}

export async function listFrames(
  sessionId: string,
  params: { limit?: number; offset?: number; only_rejected?: boolean },
): Promise<FrameList> {
  const { data } = await apiClient.get<FrameList>(
    `/ai/pipeline/sessions/${sessionId}/frames`,
    { params },
  );
  return data;
}

export async function listTracks(sessionId: string): Promise<PipelineTrack[]> {
  const { data } = await apiClient.get<PipelineTrack[]>(
    `/ai/pipeline/sessions/${sessionId}/tracks`,
  );
  return data;
}

export async function getFrameDetail(frameId: string): Promise<FrameDetail> {
  const { data } = await apiClient.get<FrameDetail>(
    `/ai/pipeline/frames/${frameId}`,
  );
  return data;
}

export async function getFrameSteps(frameId: string): Promise<FrameSteps> {
  const { data } = await apiClient.get<FrameSteps>(
    `/ai/pipeline/frames/${frameId}/steps`,
  );
  return data;
}
