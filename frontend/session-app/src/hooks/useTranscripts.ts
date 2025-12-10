import { useEffect, useMemo, useRef, useState } from 'react';
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
  isMuted?: boolean,
) {
  const [transcripts, setTranscripts] = useState<LiveTranscript[]>([]);
  const isMutedRef = useRef(isMuted);

  // ミュート状態をrefに同期
  useEffect(() => {
    isMutedRef.current = isMuted;
    if (meetingId) {
      console.log('[useTranscripts] Mute status changed:', isMuted ? 'MUTED' : 'UNMUTED');
    }
  }, [isMuted, meetingId]);

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
            const data = JSON.parse(event.data);
            console.log('[useTranscripts] Parsed data:', data);
            
            if (data?.type === 'realtime_classification') {
              console.log('[useTranscripts] Classification payload:', data.payload);
              onClassification?.(data.payload);
              return;
            }
            
            if (data?.type === 'transcript') {
              const payload = data.payload;
              const action = data.action || 'append';
              
              console.log('[useTranscripts] Transcript update:', { action, payload });
              
              setTranscripts((prev) => {
                const key = payload.result_id ?? `idx-${payload.index}`;
                
                const updateExisting = (items: LiveTranscript[]) =>
                  items.map((item) => {
                    const itemKey = (item as any).result_id ?? `idx-${(item as any).index}`;
                    if (itemKey !== key) return item;
                    
                    return {
                      meetingId,
                      transcript: payload.text || '',
                      sentiment: 'NEUTRAL',
                      timestamp: payload.timestamp || item.timestamp,
                      speaker: payload.speaker || item.speaker,
                      isPartial: false,
                      // Keep additional properties for key management
                      ...(item as any),
                      ...payload,
                    } as LiveTranscript;
                  });
                
                const exists = prev.some((item) => {
                  const itemKey = (item as any).result_id ?? `idx-${(item as any).index}`;
                  return itemKey === key;
                });
                
                if (action === 'append') {
                  if (exists) {
                    return updateExisting(prev);
                  }
                  
                  const newEntry: LiveTranscript = {
                    meetingId,
                    transcript: payload.text || '',
                    sentiment: 'NEUTRAL',
                    timestamp: payload.timestamp || new Date().toISOString(),
                    speaker: payload.speaker || 'Unknown',
                    isPartial: false,
                    // Add additional properties for key management
                    ...(payload as any),
                  };
                  
                  return [newEntry, ...prev].slice(0, 50);
                }
                
                if (action === 'update' && exists) {
                  return updateExisting(prev);
                }
                
                return prev;
              });
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
        
        audioContext = new AudioContext({ sampleRate: 16000 });
        
        if (audioContext.state === 'suspended') {
          await audioContext.resume();
        }
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        
        source.connect(processor);
        processor.connect(audioContext.destination);
        
        let audioSentCount = 0;
        
        processor.onaudioprocess = (event) => {
          if (!ws || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          
          // ミュート状態の場合は音声を送信しない
          if (isMutedRef.current) {
            // ミュート中であることを定期的にログ出力
            if (audioSentCount % 200 === 0) {
              console.log('[useTranscripts] Audio blocked due to mute');
            }
            return;
          }
          
          const input = event.inputBuffer.getChannelData(0);
          
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
            
            if (audioSentCount % 100 === 0) {
              console.log(`[useTranscripts] Sent audio packet #${audioSentCount} (muted: ${isMutedRef.current})`);
            }
          } catch (err) {
            console.error('[useTranscripts] Failed to send audio data:', err);
          }
        };
        
        console.log('[useTranscripts] Audio processing started');
        
      } catch (err) {
        console.error('[useTranscripts] Microphone setup failed:', err);
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
