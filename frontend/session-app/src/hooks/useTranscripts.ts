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

export function useTranscripts(
  meetingId?: string,
  onClassification?: (payload: any) => void,
) {
  const [transcripts, setTranscripts] = useState<LiveTranscript[]>([]);

  useEffect(() => {
    if (!meetingId) {
      console.log('[useTranscripts] No meetingId, clearing transcripts');
      setTranscripts([]);
      return;
    }

    console.log('[useTranscripts] Starting with meetingId:', meetingId);

    let audioContext: AudioContext | null = null;
    let mediaStream: MediaStream | null = null;
    let processor: ScriptProcessorNode | null = null;
    let ws: WebSocket | null = null;

    const wsUrl = buildWsUrl(meetingId);
    console.log('[useTranscripts] Connecting to WebSocket:', wsUrl);
    
    const initializeConnection = async () => {
      try {
        // Step 1: Initialize WebSocket
        ws = new WebSocket(wsUrl);
        
        ws.onopen = async () => {
          console.log('[useTranscripts] WebSocket connected, starting microphone...');
          await startMicrophone();
        };
        
        ws.onmessage = (event) => {
          console.log('[useTranscripts] Received message:', event.data);
          try {
            const payload = JSON.parse(event.data);
            console.log('[useTranscripts] Parsed payload:', payload);
            
            if (payload?.type === 'realtime_classification') {
              console.log('[useTranscripts] Classification payload:', payload.payload);
              onClassification?.(payload.payload);
              return;
            }
            
            // Only process if there's actual transcript content
            if (payload.transcript && payload.transcript.trim()) {
              const entry: LiveTranscript = {
                meetingId,
                transcript: payload.transcript.trim(),
                sentiment: payload.sentiment ?? 'NEUTRAL',
                timestamp: payload.timestamp ?? new Date().toISOString(),
                speaker: payload.speaker,
                isPartial: payload.is_partial,
              };
              console.log('[useTranscripts] Adding transcript entry:', entry);
              setTranscripts((prev) => [entry, ...prev].slice(0, 50));
            }
          } catch (err) {
            console.warn('Failed to parse transcript payload', err);
          }
        };
        
        ws.onerror = (err) => {
          console.error('[useTranscripts] WebSocket error:', err);
        };
        
        ws.onclose = (event) => {
          console.log('[useTranscripts] WebSocket closed:', event.code, event.reason);
        };

      } catch (err) {
        console.error('[useTranscripts] Failed to initialize WebSocket:', err);
      }
    };

    const startMicrophone = async () => {
      try {
        console.log('[useTranscripts] Requesting microphone access...');
        
        // Request microphone with specific constraints
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
          audio: {
            sampleRate: 16000,
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true
          }, 
          video: false 
        });
        
        console.log('[useTranscripts] Microphone access granted');
        
        // Create audio context
        audioContext = new AudioContext({ sampleRate: 16000 });
        
        // Resume audio context if suspended (required by some browsers)
        if (audioContext.state === 'suspended') {
          await audioContext.resume();
          console.log('[useTranscripts] Audio context resumed');
        }
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        
        source.connect(processor);
        processor.connect(audioContext.destination);
        
        let audioSentCount = 0;
        let silenceCount = 0;
        
        processor.onaudioprocess = (event) => {
          if (!ws || ws.readyState !== WebSocket.OPEN) {
            if (audioSentCount % 100 === 0) {
              console.log('[useTranscripts] WebSocket not ready, readyState:', ws?.readyState);
            }
            return;
          }
          
          const input = event.inputBuffer.getChannelData(0);
          
          // Check for actual audio activity
          let hasAudio = false;
          let maxAmplitude = 0;
          for (let i = 0; i < input.length; i++) {
            const amplitude = Math.abs(input[i]);
            maxAmplitude = Math.max(maxAmplitude, amplitude);
            if (amplitude > 0.01) { // Threshold for detecting audio
              hasAudio = true;
            }
          }
          
          if (!hasAudio) {
            silenceCount++;
            if (silenceCount % 100 === 0) {
              console.log('[useTranscripts] Silence detected, max amplitude:', maxAmplitude);
            }
          } else {
            if (silenceCount > 0) {
              console.log('[useTranscripts] Audio detected! Max amplitude:', maxAmplitude);
              silenceCount = 0;
            }
          }
          
          // Convert to 16-bit PCM
          const buffer = new ArrayBuffer(input.length * 2);
          const view = new DataView(buffer);
          for (let i = 0; i < input.length; i++) {
            let sample = input[i];
            sample = Math.max(-1, Math.min(1, sample));
            view.setInt16(i * 2, sample * 0x7fff, true);
          }
          
          try {
            ws.send(buffer);
            audioSentCount++;
            
            if (audioSentCount % 50 === 0) {
              console.log(`[useTranscripts] Sent audio packet #${audioSentCount}, hasAudio: ${hasAudio}, maxAmp: ${maxAmplitude.toFixed(4)}`);
            }
          } catch (err) {
            console.error('[useTranscripts] Failed to send audio data:', err);
          }
        };
        
        console.log('[useTranscripts] Audio processing started');
      } catch (err) {
        console.error('[useTranscripts] Microphone setup failed:', err);
        
        // Try to provide helpful error messages
        if (err instanceof DOMException) {
          if (err.name === 'NotAllowedError') {
            console.error('[useTranscripts] Microphone access denied by user');
          } else if (err.name === 'NotFoundError') {
            console.error('[useTranscripts] No microphone found');
          } else if (err.name === 'NotReadableError') {
            console.error('[useTranscripts] Microphone is being used by another application');
          }
        }
      }
    };

    // Start the initialization process
    initializeConnection();

    return () => {
      console.log('[useTranscripts] Cleaning up...');
      
      if (ws) {
        ws.close();
      }
      if (processor) {
        processor.disconnect();
        processor.onaudioprocess = null;
      }
      if (mediaStream) {
        mediaStream.getTracks().forEach((track) => {
          track.stop();
          console.log('[useTranscripts] Stopped media track:', track.kind);
        });
      }
      if (audioContext && audioContext.state !== 'closed') {
        audioContext.close();
      }
    };
  }, [meetingId]);

  const latest = useMemo(() => transcripts[0], [transcripts]);

  return { transcripts, latest };
}
