import { useState } from 'react';
import type { MeetingSession, Participant } from '../types';
import { createMeetingSession, joinMeeting } from '../services/api';

export function useMeetingSession() {
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
      setSession(data);
      setStatus('connected');
    } catch (err) {
      setStatus('error');
      setSession(null);
      const message = err instanceof Error ? err.message : '参加に失敗しました';
      setError(message);
      throw err;
    }
  };

  const create = async (title: string, scheduledFor?: string) => {
    setStatus('connecting');
    setError(null);
    try {
      const data = await createMeetingSession(title, scheduledFor);
      setSession(data);
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
