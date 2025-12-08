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

    let audioContext: AudioContext | null = null;
    let mediaStream: MediaStream | null = null;
    let processor: ScriptProcessorNode | null = null;

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
          isPartial: payload.is_partial,
        };
        setTranscripts((prev) => [entry, ...prev].slice(0, 50));
      } catch (err) {
        console.warn('Failed to parse transcript payload', err);
      }
    };
    ws.onerror = (err) => console.error('Transcript websocket error', err);
    ws.onerror = (err) => console.error('Transcript websocket error', err);

    const startMic = async () => {
      try {
        audioContext = new AudioContext({ sampleRate: 16000 });
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(audioContext.destination);
        processor.onaudioprocess = (event) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const input = event.inputBuffer.getChannelData(0);
          const buffer = new ArrayBuffer(input.length * 2);
          const view = new DataView(buffer);
          for (let i = 0; i < input.length; i += 1) {
            let sample = input[i];
            sample = Math.max(-1, Math.min(1, sample));
            view.setInt16(i * 2, sample * 0x7fff, true);
          }
          ws.send(buffer);
        };
      } catch (err) {
        console.error('Microphone capture failed', err);
      }
    };

    startMic();

    return () => {
      ws.close();
      if (processor) {
        processor.disconnect();
        processor.onaudioprocess = null;
      }
      if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
      }
      if (audioContext) {
        audioContext.close();
      }
    };
  }, [meetingId]);

  const latest = useMemo(() => transcripts[0], [transcripts]);

  return { transcripts, latest };
}
