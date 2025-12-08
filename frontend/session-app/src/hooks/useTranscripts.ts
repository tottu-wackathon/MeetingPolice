import { useEffect, useMemo, useState } from 'react';
import type { LiveTranscript } from '../types';

const buildWsUrl = (meetingId: string) => {
  const apiBase = import.meta.env.VITE_API_BASE ?? '/api';
  if (apiBase.startsWith('http')) {
    const url = new URL(apiBase);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const basePath = url.pathname.endsWith('/') ? url.pathname.slice(0, -1) : url.pathname;
    return `${url.origin}${basePath}/session/ws/${meetingId}`;
  }
  const origin = window.location.origin.replace(/^http/, 'ws');
  const base = apiBase.endsWith('/') ? apiBase.slice(0, -1) : apiBase;
  return `${origin}${base}/session/ws/${meetingId}`;
};

export function useTranscripts(meetingId?: string) {
  const [transcripts, setTranscripts] = useState<LiveTranscript[]>([]);

  useEffect(() => {
    if (!meetingId) {
      setTranscripts([]);
      return;
    }

    const ws = new WebSocket(buildWsUrl(meetingId));
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const entry: LiveTranscript = {
          meetingId,
          transcript: payload.transcript ?? '',
          sentiment: payload.sentiment ?? 'NEUTRAL',
          timestamp: payload.timestamp ?? new Date().toISOString(),
          speaker: payload.speaker,
        };
        setTranscripts((prev) => [entry, ...prev].slice(0, 50));
      } catch (err) {
        console.warn('Failed to parse transcript payload', err);
      }
    };
    ws.onerror = (err) => console.error('Transcript websocket error', err);
    return () => ws.close();
  }, [meetingId]);

  const latest = useMemo(() => transcripts[0], [transcripts]);

  return { transcripts, latest };
}
