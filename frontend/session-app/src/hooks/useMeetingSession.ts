import { useState } from 'react';
import type { MeetingSession, Participant } from '../types';
import { createMeetingSession, joinMeeting } from '../services/api';

export function useMeetingSession() {
  const envApiKey = import.meta.env.VITE_VONAGE_APP_ID as string | undefined;
  const envSessionId = import.meta.env.VITE_VONAGE_SESSION_ID as string | undefined;
  const envToken = import.meta.env.VITE_VONAGE_TOKEN as string | undefined;
  const hasEnvSession = Boolean(envApiKey && envSessionId && envToken);

  const [session, setSession] = useState<MeetingSession | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);
  const [handRaised, setHandRaised] = useState(false);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const connect = async (meetingId: string) => {
    setStatus('connecting');
    setError(null);
    try {
      const data = await joinMeeting(meetingId.trim());
      const videoEnabled = Boolean(data.apiKey && data.sessionId && data.token);
      setSession({ ...data, videoEnabled });
      setStatus('connected');
      return { ...data, videoEnabled };
    } catch (err) {
      // Vonage API 取得に失敗した場合は、環境変数の固定セッションか音声のみのフォールバックに切り替える
      const message = err instanceof Error ? err.message : '参加に失敗しました';
      setError(message);

      if (hasEnvSession) {
        const fallbackSession: MeetingSession = {
          meetingId: meetingId.trim() || 'static-meeting',
          title: 'Static Vonage Session',
          status: 'live',
          sessionId: envSessionId!,
          token: envToken!,
          apiKey: envApiKey!,
          videoEnabled: true,
          participants: [],
        };
        setSession(fallbackSession);
        setStatus('connected');
        return fallbackSession;
      }

      const audioOnly: MeetingSession = {
        meetingId: meetingId.trim() || 'audio-only',
        title: 'Audio-only session',
        status: 'audio-only',
        sessionId: '',
        token: '',
        apiKey: '',
        videoEnabled: false,
        participants: [],
      };
      setSession(audioOnly);
      setStatus('connected');
      return audioOnly;
    }
  };

  const create = async (title: string, scheduledFor?: string) => {
    setStatus('connecting');
    setError(null);
    try {
      const data = await createMeetingSession(title, scheduledFor);
      const videoEnabled = Boolean(data.apiKey && data.sessionId && data.token);
      setSession({ ...data, videoEnabled });
      setStatus('connected');
    } catch (err) {
      setStatus('error');
      setSession(null);
      const message = err instanceof Error ? err.message : 'セッションの作成に失敗しました';
      setError(message);
      throw err;
    }
  };

  const leave = () => {
    setSession(null);
    setStatus('idle');
    setIsMuted(false);
    setIsVideoOff(false);
    setHandRaised(false);
  };

  const toggleMute = () => setIsMuted((prev) => !prev);
  const toggleVideo = () => setIsVideoOff((prev) => !prev);
  const toggleHand = () => setHandRaised((prev) => !prev);

  const updateParticipantSpeaking = (id: string, isSpeaking: boolean) => {
    setSession((prev) => {
      if (!prev) return prev;
      const participants: Participant[] = prev.participants.map((p) =>
        p.id === id ? { ...p, isSpeaking } : p
      );
      return { ...prev, participants };
    });
  };

  return {
    session,
    isMuted,
    isVideoOff,
    handRaised,
    status,
    error,
    createMeeting: create,
    joinMeeting: connect,
    leaveMeeting: leave,
    toggleMute,
    toggleVideo,
    toggleHand,
    updateParticipantSpeaking,
  };
}
