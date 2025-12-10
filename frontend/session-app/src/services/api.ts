import type {
  MeetingSession,
  PocAnalysisResult,
  PocClassifiedSegment,
  PocJobDetail,
  PocArchivedJob,
  PocHistoryItem,
} from '../types';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';

const fallbackMessages: Record<number, string> = {
  404: '入力されたIDのミーティングは開催されていません',
};

async function request<T>(path: string, init?: RequestInit, addJsonHeader = true): Promise<T> {
  const headers = addJsonHeader
    ? { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
    : init?.headers;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    let message: string | undefined;
    if (contentType.includes('application/json')) {
      try {
        const body = await response.json();
        if (typeof body?.detail === 'string') {
          message = body.detail;
        } else if (typeof body?.message === 'string') {
          message = body.message;
        } else {
          message = JSON.stringify(body);
        }
      } catch {
        /* fall back to text below */
      }
    }
    if (!message) {
      const text = await response.text();
      message = text || `${response.status} ${response.statusText || 'Error'}`;
    }
    if (response.status in fallbackMessages) {
      const fallback = fallbackMessages[response.status];
      if (!message || /not\s+found/i.test(message)) {
        message = fallback;
      }
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export async function joinMeeting(meetingId: string): Promise<MeetingSession> {
  const response = await request<{
    meeting_id: string;
    title: string;
    status: string;
    session_id: string;
    token: string;
    api_key: string;
  }>(`/session/meetings/${meetingId}/join`, { method: 'POST' });

  return {
    meetingId: response.meeting_id,
    title: response.title,
    status: response.status,
    sessionId: response.session_id,
    token: response.token,
    apiKey: response.api_key,
    videoEnabled: Boolean(response.api_key && response.session_id && response.token),
    participants: [
      { id: 'me', name: 'You', role: 'host', isSpeaking: false },
      { id: 'cohost', name: 'Co-host', role: 'guest', isSpeaking: true },
    ],
  };
}

export async function createMeetingSession(title: string, scheduledFor?: string): Promise<MeetingSession> {
  const response = await request<{
    meeting_id: string;
    title: string;
    status: string;
    session_id: string;
    token: string;
    api_key: string;
  }>('/session/meetings', {
    method: 'POST',
    body: JSON.stringify({ title, scheduled_for: scheduledFor }),
  });

  return {
    meetingId: response.meeting_id,
    title: response.title,
    status: response.status,
    sessionId: response.session_id,
    token: response.token,
    apiKey: response.api_key,
    videoEnabled: Boolean(response.api_key && response.session_id && response.token),
    participants: [
      { id: 'host', name: 'Host', role: 'host', isSpeaking: false },
    ],
  };
}

export async function startPocRun(formData: FormData): Promise<{ job_id: string }> {
  return request<{ job_id: string }>('/poc/start', { method: 'POST', body: formData }, false);
}

export async function fetchPocJob(jobId: string): Promise<PocJobDetail> {
  return request<PocJobDetail>(`/poc/jobs/${jobId}`);
}

export async function analyzePocJob(jobId: string): Promise<PocAnalysisResult> {
  return request<PocAnalysisResult>(`/poc/jobs/${jobId}/analyze`, { method: 'POST' });
}

export async function classifyPocJob(
  jobId: string,
  refresh = false,
): Promise<{ job_id: string; classified_segments: PocClassifiedSegment[] }> {
  const query = refresh ? '?refresh=true' : '';
  return request<{ job_id: string; classified_segments: PocClassifiedSegment[] }>(
    `/poc/jobs/${jobId}/classify${query}`,
    { method: 'POST' },
  );
}

export async function fetchPocHistory(): Promise<PocHistoryItem[]> {
  return request<PocHistoryItem[]>(`/poc/history`);
}

export async function fetchArchivedJob(jobId: string): Promise<PocArchivedJob> {
  return request<PocArchivedJob>(`/poc/history/${jobId}`);
}

export async function classifyArchivedJob(
  jobId: string,
): Promise<{ job_id: string; classified_segments: PocClassifiedSegment[] }> {
  return request<{ job_id: string; classified_segments: PocClassifiedSegment[] }>(
    `/poc/history/${jobId}/classify`,
    { method: 'POST' },
  );
}

// PoC Satomin API
export async function startPocSatominRun(formData: FormData): Promise<{ job_id: string }> {
  return request<{ job_id: string }>('/poc_satomin/start', { method: 'POST', body: formData }, false);
}

export async function fetchPocSatominJob(jobId: string): Promise<PocJobDetail> {
  return request<PocJobDetail>(`/poc_satomin/jobs/${jobId}`);
}

export async function fetchPocSatominHistory(): Promise<PocHistoryItem[]> {
  return request<PocHistoryItem[]>(`/poc_satomin/history`);
}

export async function fetchArchivedSatominJob(jobId: string): Promise<PocArchivedJob> {
  return request<PocArchivedJob>(`/poc_satomin/history/${jobId}`);
}
