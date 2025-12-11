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
  onPoliceDispatch?: (payload: any) => void,
  onAlignmentWarning?: (payload: any) => void,
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
            const payload = JSON.parse(event.data);
            const messageType = payload?.type;
            const action = payload?.action;
            console.log('[useTranscripts] Parsed payload:', payload);
            
            if (messageType === 'realtime_classification') {
              console.log('[useTranscripts] Classification payload:', payload.payload);
              onClassification?.(payload.payload);
              return;
            }
            
            // 警察出動通知の処理
            if (messageType === 'police_dispatch') {
              console.log('🚨 [useTranscripts] Police dispatch notification received:', payload);
              onPoliceDispatch?.(payload);
              return;
            }
            
            // アライメント警告の処理
            if (messageType === 'alignment_warning') {
              console.log('⚠️ [useTranscripts] Alignment warning received:', payload);
              onAlignmentWarning?.(payload);
              return;
            }
            
            // 警察出動解除通知の処理
            if (messageType === 'police_dispatch_off') {
              console.log('🟢 [useTranscripts] Police dispatch OFF notification received:', payload);
              onPoliceDispatch?.(payload);  // 同じコールバックを使用して解除通知も処理
              return;
            }
            
            // transcriptメッセージを抽出（queue経由のpayloadラップにも対応）
            const transcriptPayload = messageType === 'transcript'
              ? payload.payload ?? {}
              : (payload.payload && typeof payload.payload === 'object' ? payload.payload : payload);
            
            const transcriptText = (transcriptPayload?.transcript ?? transcriptPayload?.text ?? '').trim();
            if (!transcriptText) {
              if (messageType === 'transcript') {
                console.log('[useTranscripts] Transcript message without text, skipping');
              }
              return;
            }

            const resolvedAction = transcriptPayload.action || action || 'new';
            const isFinalize = resolvedAction === 'finalize' || resolvedAction === 'final';
            const entry: LiveTranscript = {
              meetingId,
              transcript: transcriptText,
              sentiment: transcriptPayload.sentiment ?? 'NEUTRAL',
              timestamp: transcriptPayload.timestamp ?? new Date().toISOString(),
              speaker: transcriptPayload.speaker ?? transcriptPayload.speaker_label ?? transcriptPayload.raw_speaker ?? '判別中...',
              isPartial: transcriptPayload.isPartial ?? transcriptPayload.is_partial ?? !isFinalize,
              index: transcriptPayload.index,
            };
            
            console.log(`[useTranscripts] Processing transcript (${resolvedAction}):`, { ...entry, transcript: transcriptText.slice(0, 60) });
            
            setTranscripts((prev) => {
              if (resolvedAction === 'update' && entry.index !== undefined) {
                // Update existing entry with same index
                const updated = prev.map(item => 
                  item.index === entry.index ? { ...item, ...entry } : item
                );
                console.log('[useTranscripts] Updated existing transcript at index:', entry.index);
                return updated;
              } else if (isFinalize && entry.index !== undefined) {
                // Finalize existing entry
                const updated = prev.map(item => 
                  item.index === entry.index ? { ...item, ...entry, isPartial: false } : item
                );
                console.log('[useTranscripts] Finalized transcript at index:', entry.index);
                return updated;
              } else {
                // Add new entry（append/new）: index重複は上書き
                if (entry.index !== undefined && prev.some(item => item.index === entry.index)) {
                  const updated = prev.map(item => 
                    item.index === entry.index ? { ...item, ...entry } : item
                  );
                  console.log('[useTranscripts] Replaced existing transcript at index:', entry.index);
                  return updated;
                }
                console.log('[useTranscripts] Adding new transcript entry');
                return [entry, ...prev].slice(0, 50);
              }
            });
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
