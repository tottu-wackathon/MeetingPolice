import { useEffect, useMemo, useState } from 'react';
import type { LiveTranscript } from '../types';

const buildWsUrl = (meetingId: string) => {
  const apiBase = (import.meta as any).env?.VITE_API_BASE ?? '/api';
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
        
        // First check if getUserMedia is available
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          throw new Error('getUserMedia is not supported in this browser');
        }
        
        // Request microphone with basic constraints first
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
          audio: true,
          video: false 
        });
        
        console.log('[useTranscripts] Microphone access granted, tracks:', mediaStream.getTracks().map(t => ({
          kind: t.kind,
          enabled: t.enabled,
          readyState: t.readyState,
          label: t.label
        })));
        
        // Create audio context with default sample rate, then resample if needed
        audioContext = new AudioContext();
        
        // Resume audio context if suspended (required by some browsers)
        if (audioContext.state === 'suspended') {
          await audioContext.resume();
          console.log('[useTranscripts] Audio context resumed');
        }
        
        console.log('[useTranscripts] Audio context created, sampleRate:', audioContext.sampleRate);
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        
        // Use larger buffer size for better performance
        const bufferSize = 4096;
        processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
        
        source.connect(processor);
        processor.connect(audioContext.destination);
        
        let audioSentCount = 0;
        let silenceCount = 0;
        let lastAudioTime = Date.now();
        
        processor.onaudioprocess = (event) => {
          if (!ws || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          
          const input = event.inputBuffer.getChannelData(0);
          
          // Check for actual audio activity
          let hasAudio = false;
          let maxAmplitude = 0;
          let rms = 0;
          
          for (let i = 0; i < input.length; i++) {
            const amplitude = Math.abs(input[i]);
            maxAmplitude = Math.max(maxAmplitude, amplitude);
            rms += input[i] * input[i];
            if (amplitude > 0.005) { // Lower threshold for better sensitivity
              hasAudio = true;
            }
          }
          
          rms = Math.sqrt(rms / input.length);
          
          if (hasAudio) {
            lastAudioTime = Date.now();
            if (silenceCount > 0) {
              console.log('[useTranscripts] Audio detected! Max amplitude:', maxAmplitude.toFixed(4), 'RMS:', rms.toFixed(4));
              silenceCount = 0;
            }
          } else {
            silenceCount++;
          }
          
          // Resample to 16kHz if needed
          let outputData = input;
          if (audioContext && audioContext.sampleRate !== 16000) {
            const ratio = audioContext.sampleRate / 16000;
            const outputLength = Math.floor(input.length / ratio);
            const resampled = new Float32Array(outputLength);
            
            for (let i = 0; i < outputLength; i++) {
              const srcIndex = Math.floor(i * ratio);
              resampled[i] = input[srcIndex];
            }
            outputData = resampled;
          }
          
          // Convert to 16-bit PCM
          const buffer = new ArrayBuffer(outputData.length * 2);
          const view = new DataView(buffer);
          for (let i = 0; i < outputData.length; i++) {
            let sample = outputData[i];
            sample = Math.max(-1, Math.min(1, sample));
            view.setInt16(i * 2, sample * 0x7fff, true);
          }
          
          try {
            ws.send(buffer);
            audioSentCount++;
            
            if (audioSentCount % 100 === 0) {
              console.log(`[useTranscripts] Sent audio packet #${audioSentCount}, hasAudio: ${hasAudio}, maxAmp: ${maxAmplitude.toFixed(4)}, timeSinceLastAudio: ${Date.now() - lastAudioTime}ms`);
            }
          } catch (err) {
            console.error('[useTranscripts] Failed to send audio data:', err);
          }
        };
        
        console.log('[useTranscripts] Audio processing started');
        
        // Send a heartbeat to keep the connection alive
        const heartbeatInterval = setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            // Send a small silence chunk to prevent timeout
            const silenceBuffer = new ArrayBuffer(320); // 10ms of silence at 16kHz
            ws.send(silenceBuffer);
          }
        }, 5000); // Every 5 seconds
        
        // Store interval for cleanup
        (processor as any).heartbeatInterval = heartbeatInterval;
        
      } catch (err) {
        console.error('[useTranscripts] Microphone setup failed:', err);
        
        // Try to provide helpful error messages
        if (err instanceof DOMException) {
          if (err.name === 'NotAllowedError') {
            console.error('[useTranscripts] Microphone access denied by user');
            alert('マイクへのアクセスが拒否されました。ブラウザの設定でマイクアクセスを許可してください。');
          } else if (err.name === 'NotFoundError') {
            console.error('[useTranscripts] No microphone found');
            alert('マイクが見つかりません。マイクが接続されているか確認してください。');
          } else if (err.name === 'NotReadableError') {
            console.error('[useTranscripts] Microphone is being used by another application');
            alert('マイクが他のアプリケーションで使用されています。');
          }
        } else {
          const message = err instanceof Error ? err.message : String(err);
          alert(`マイクの初期化に失敗しました: ${message}`);
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
        // Clear heartbeat interval
        if ((processor as any).heartbeatInterval) {
          clearInterval((processor as any).heartbeatInterval);
        }
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
