import { useEffect, useState } from 'react';
import { MeetingForm } from '../components/MeetingForm';
import { MeetingTable } from '../components/MeetingTable';
import { SummaryPanel } from '../components/SummaryPanel';
import { useMeetings } from '../hooks/useMeetings';
import type { Meeting } from '../types';

export function MeetingsPage() {
  const { meetings, loading, error, refetch } = useMeetings();
  const [selected, setSelected] = useState<Meeting | null>(null);

  useEffect(() => {
    if (!selected && meetings.length > 0) {
      setSelected(meetings[0]);
    }
  }, [meetings, selected]);

  const handleCreated = (meeting: Meeting) => {
    setSelected(meeting);
    refetch();
  };

  if (loading) {
    return <p className="page">Loading meetings…</p>;
  }

  if (error) {
    return (
      <div className="page">
        <p role="alert">Could not load meetings: {error}</p>
        <button type="button" onClick={refetch}>
          Retry
        </button>
      </div>
    );
  }

  const latestId = selected?.meetingId ?? meetings[0]?.meetingId ?? '未作成';

  return (
    <div className="page">
      <section className="hero">
        <div className="hero-content">
          <p className="eyebrow">MeetingPolice 管理コンソール</p>
          <h1>セッションを用意して Meeting ID を参加者へ共有</h1>
          <p className="hero-subtitle">
            ミーティングを作成 → 共有 → 進行状況を確認するまでを 1 つの画面で完結できます。
          </p>
          <div className="steps-grid">
            <div className="step-card">
              <span>1</span>
              <p>ミーティングを作成</p>
            </div>
            <div className="step-card">
              <span>2</span>
              <p>Meeting ID を共有</p>
            </div>
            <div className="step-card">
              <span>3</span>
              <p>Session ページで参加</p>
            </div>
          </div>
        </div>
        <div className="hero-card">
          <p className="label">最新の Meeting ID</p>
          <p className="hero-id">{latestId}</p>
          <p className="help-text">この ID を参加者へ渡してください。</p>
          <button type="button" onClick={refetch} className="ghost">
            最新情報を取得
          </button>
        </div>
      </section>

      <div className="grid">
        <div>
          <MeetingForm onCreated={handleCreated} />
          <MeetingTable meetings={meetings} onSelect={setSelected} />
        </div>
        <SummaryPanel meeting={selected} />
      </div>
    </div>
  );
}
