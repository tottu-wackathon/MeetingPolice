import { useState } from 'react';
import { joinMeeting, type MeetingSession } from './services/api';
import { useVonageSession } from './hooks/useVonageSession';
import { VideoPublisher } from './components/VideoPublisher';
import { VideoSubscriber } from './components/VideoSubscriber';
import { ControlBar } from './components/ControlBar';
import './App.css';

function App() {
  const [meetingId, setMeetingId] = useState('');
  const [session, setSession] = useState<MeetingSession | null>(null);
  const [isJoining, setIsJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  const vonageSession = useVonageSession({
    apiKey: session?.api_key || '',
    sessionId: session?.session_id || '',
    token: session?.token || '',
  });

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!meetingId.trim()) return;

    setIsJoining(true);
    setJoinError(null);

    try {
      const sessionData = await joinMeeting(meetingId.trim());
      setSession(sessionData);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to join meeting';
      setJoinError(message);
      console.error('Join error:', error);
    } finally {
      setIsJoining(false);
    }
  };

  const handleLeave = () => {
    vonageSession.disconnect();
    setSession(null);
    setMeetingId('');
    setJoinError(null);
  };

  if (!session) {
    return (
      <div className="app">
        <div className="join-container">
          <h1>ビデオ会議に参加</h1>
          
          <form onSubmit={handleJoin} className="join-form">
            <div className="form-group">
              <label htmlFor="meetingId">Meeting ID</label>
              <input
                id="meetingId"
                type="text"
                value={meetingId}
                onChange={(e) => setMeetingId(e.target.value)}
                placeholder="Meeting IDを入力してください"
                disabled={isJoining}
              />
            </div>
            
            <button type="submit" disabled={isJoining || !meetingId.trim()}>
              {isJoining ? '接続中...' : '参加する'}
            </button>
          </form>

          {joinError && (
            <div className="error-message">
              <h3>接続エラー</h3>
              <p>{joinError}</p>
              
              {joinError.includes('1004') && (
                <div className="error-details">
                  <h4>解決方法:</h4>
                  <ul>
                    <li>バックエンドのVonage API設定を確認してください</li>
                    <li>Meeting IDが正しいか確認してください</li>
                    <li>ネットワーク接続を確認してください</li>
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="meeting-container">
        <div className="meeting-header">
          <h1>{session.title}</h1>
          <span className="meeting-id">Meeting ID: {session.meeting_id}</span>
        </div>

        {vonageSession.error && (
          <div className="error-message">
            <p>Vonage接続エラー: {vonageSession.error}</p>
          </div>
        )}

        <div className="video-grid">
          {/* Publisher (Self) */}
          {vonageSession.publisher && (
            <div className="video-tile">
              <VideoPublisher
                publisher={vonageSession.publisher}
                isAudioEnabled={vonageSession.isAudioEnabled}
                isVideoEnabled={vonageSession.isVideoEnabled}
              />
            </div>
          )}

          {/* Subscribers (Remote participants) */}
          {vonageSession.subscribers.map((subscriber, index) => (
            <div key={index} className="video-tile">
              <VideoSubscriber
                subscriber={subscriber}
                stream={subscriber.stream}
              />
            </div>
          ))}

          {/* Empty state */}
          {vonageSession.subscribers.length === 0 && vonageSession.isConnected && (
            <div className="video-tile empty">
              <div className="empty-message">
                <p>他の参加者を待っています...</p>
              </div>
            </div>
          )}
        </div>

        <ControlBar
          isAudioEnabled={vonageSession.isAudioEnabled}
          isVideoEnabled={vonageSession.isVideoEnabled}
          onToggleAudio={vonageSession.toggleAudio}
          onToggleVideo={vonageSession.toggleVideo}
          onLeave={handleLeave}
        />

        <div className="connection-status">
          <span className={`status ${vonageSession.isConnected ? 'connected' : 'connecting'}`}>
            {vonageSession.isConnected ? '🟢 接続済み' : '🟡 接続中...'}
          </span>
        </div>
      </div>
    </div>
  );
}

export default App;