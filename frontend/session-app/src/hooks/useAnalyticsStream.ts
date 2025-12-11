import { useEffect, useMemo, useState } from 'react';
import type { AnalyticsSample } from '../types';
import { formatTime } from '../utils/time';

const sentiments: AnalyticsSample['sentiment'][] = ['POSITIVE', 'NEUTRAL', 'NEGATIVE'];

function createSample(overrides: Partial<AnalyticsSample> = {}): AnalyticsSample {
  return {
    timestamp: formatTime(new Date()),
    sentiment: sentiments[Math.floor(Math.random() * sentiments.length)],
    energyScore: Number((Math.random() * 1).toFixed(2)),
    talkTimeSeconds: Math.floor(Math.random() * 300),
    ...overrides,
  };
}

function buildWsUrl(meetingId: string): string {
  const base = import.meta.env.VITE_API_BASE ?? '/api';
  if (base.startsWith('http')) {
    return `${base.replace(/^http/, 'ws')}/session/ws/${meetingId}`;
  }
  const { protocol, host } = window.location;
  const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:';
  const trimmedBase = base.endsWith('/') ? base.slice(0, -1) : base;
  return `${wsProtocol}//${host}${trimmedBase}/session/ws/${meetingId}`;
}

export function useAnalyticsStream(meetingId?: string) {
  const [samples, setSamples] = useState<AnalyticsSample[]>([]);

  useEffect(() => {
    if (!meetingId) {
      const interval = setInterval(() => {
        setSamples((prev) => [createSample(), ...prev].slice(0, 5));
      }, 4000);
      return () => clearInterval(interval);
    }

    const ws = new WebSocket(buildWsUrl(meetingId));
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const sample = createSample({
          timestamp: formatTime(payload.timestamp ?? new Date()),
          sentiment: payload.sentiment ?? 'NEUTRAL',
          energyScore: Number(Math.random().toFixed(2)),
          talkTimeSeconds: Math.floor(Math.random() * 300),
        });
        setSamples((prev) => [sample, ...prev].slice(0, 5));
      } catch (err) {
        console.warn('Failed to parse WS payload', err);
      }
    };
    ws.onerror = (err) => console.error('WS error', err);
    return () => ws.close();
  }, [meetingId]);

  const latest = useMemo(() => samples[0], [samples]);

  return { samples, latest };
}
