import { PropsWithChildren } from 'react';

type Props = PropsWithChildren<{
  title?: string;
  subtitle?: string;
}>;

export function Layout({
  children,
  title = 'MeetingPolice Session',
  subtitle = '参加者はここで Meeting ID を入力し、音声解析の結果をリアルタイムに確認します。',
}: Props) {
  return (
    <div className="mp-session-layout">
      <header>
        <h1>{title}</h1>
        <p style={{ textAlign: 'center', width: '100%', margin: '1rem 0 0 0' }}>{subtitle}</p>
      </header>
      <main>{children}</main>
    </div>
  );
}
