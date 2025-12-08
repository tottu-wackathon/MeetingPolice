import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Layout } from '../components/Layout';

interface ResultData {
    agendaText: string;
    elapsedSeconds: number;
    avgAlignment: number;
    totalItems: number;
    scheduledMinutes?: number;
    speakerCounts?: { [key: string]: number };
    speakerNames?: { [key: string]: string };
}

export function ResultPage() {
    const location = useLocation();
    const navigate = useNavigate();
    const [resultData, setResultData] = useState<ResultData | null>(null);

    useEffect(() => {
        // location.state が undefined でも落ちないようにガード
        const data = location.state as ResultData | undefined;
        if (!data) {
            // データがない場合は元のページに戻る
            navigate('/poc_satomin');
            return;
        }
        setResultData(data);
    }, [location.state, navigate]);

    // resultData がまだ無い場合でも hook の順序を崩さないように、デフォルト値で計算する
    const agendaText = resultData?.agendaText ?? '';
    const elapsedSeconds = resultData?.elapsedSeconds ?? 0;
    const avgAlignment = resultData?.avgAlignment ?? 0;
    const totalItems = resultData?.totalItems ?? 0;
    const scheduledMinutes = resultData?.scheduledMinutes;
    const speakerCounts = resultData?.speakerCounts;
    const speakerNames = resultData?.speakerNames;
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = elapsedSeconds % 60;
    const isSuccess = avgAlignment >= 60;

    const confetti = useMemo(() => {
        if (!isSuccess) return [];
        const palette = ['#ff8a65', '#ffd54f', '#4fc3f7', '#ba68c8', '#00e676', '#ff5252', '#ffee58', '#80deea'];
        const rand = (seed: number) => {
            const x = Math.sin(seed) * 10000;
            return x - Math.floor(x);
        };
        return Array.from({ length: 120 }).map((_, i) => ({
            id: i,
            left: rand(i) * 100,
            delay: rand(i + 1) * 0.6,
            duration: 4 + rand(i + 2) * 2.5,
            color: palette[Math.floor(rand(i + 3) * palette.length)],
            rotation: rand(i + 4) * 360,
            scale: 0.7 + rand(i + 5) * 0.9,
            width: 6 + rand(i + 6) * 10,
            height: 10 + rand(i + 7) * 14,
            drift: (rand(i + 8) - 0.5) * 50, // 左右に少し流れる
        }));
    }, [isSuccess]);

    // 話者別発言割合を計算
    const speakerStats = speakerCounts ? Object.entries(speakerCounts).map(([speaker, count]) => {
        const totalCount = Object.values(speakerCounts).reduce((sum, c) => sum + c, 0);
        return {
            speaker,
            count,
            percentage: Math.round((count / totalCount) * 100)
        };
    }).sort((a, b) => b.count - a.count) : [];

    return (
        <Layout title="ミーティング結果" subtitle="お疲れさまでした！">
            <div style={{ maxWidth: '800px', margin: '0 auto' }}>
                {isSuccess && confetti.length > 0 && (
                    <div className="confetti-container">
                        {confetti.map((piece) => (
                            <span
                                key={piece.id}
                                className="confetti-piece"
                                style={{
                                    left: `${piece.left}%`,
                                    animation: `mpConfettiFall ${piece.duration}s linear ${piece.delay}s forwards`,
                                    backgroundColor: piece.color,
                                    transform: `rotate(${piece.rotation}deg) scale(${piece.scale})`,
                                    willChange: 'transform, opacity',
                                    width: `${piece.width}px`,
                                    height: `${piece.height}px`,
                                    ['--drift' as string]: `${piece.drift}px`,
                                }}
                            />
                        ))}
                    </div>
                )}

                {isSuccess && (
                    <div style={{
                        padding: '32px',
                        textAlign: 'center',
                        backgroundColor: '#4caf50',
                        color: 'white',
                        borderRadius: '12px',
                        marginBottom: '24px',
                        fontSize: '2em',
                        fontWeight: 'bold'
                    }}>
                        ✨ 🪩 🎉 おめでとう！ 🎉 🪩 ✨
                    </div>
                )}

                <section className="panel" style={{ marginBottom: '24px' }}>
                    <h2>📊 ミーティング結果</h2>

                    <div style={{ marginTop: '24px' }}>
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: '1fr 1fr',
                            gap: '16px',
                            marginBottom: '24px'
                        }}>
                            <div style={{
                                padding: '20px',
                                backgroundColor: 'rgba(10, 14, 39, 0.9)',
                                borderRadius: '8px',
                                textAlign: 'center',
                                border: '2px solid #00ffff'
                            }}>
                                <p style={{ margin: '0 0 8px 0', fontSize: '0.9em', color: '#00ffff' }}>
                                    ⏱️ 経過時間
                                </p>
                                <div style={{ fontSize: '2.5em', fontWeight: 'bold', color: '#00ffff' }}>
                                    {minutes}:{seconds.toString().padStart(2, '0')}
                                </div>
                                {scheduledMinutes && (
                                    <p style={{ margin: '8px 0 0 0', fontSize: '0.9em', color: '#00ffff' }}>
                                        / {scheduledMinutes}分
                                    </p>
                                )}
                            </div>

                            <div style={{
                                padding: '20px',
                                backgroundColor: 'rgba(10, 14, 39, 0.9)',
                                borderRadius: '8px',
                                textAlign: 'center',
                                border: '2px solid #00ffff'
                            }}>
                                <p style={{ margin: '0 0 8px 0', fontSize: '0.9em', color: '#00ffff' }}>
                                    📈 平均一致度
                                </p>
                                <div style={{
                                    fontSize: '2.5em',
                                    fontWeight: 'bold',
                                    color: avgAlignment >= 60 ? '#4caf50' : avgAlignment >= 40 ? '#ff9800' : '#f44336'
                                }}>
                                    {avgAlignment}%
                                </div>
                                <p style={{ margin: '8px 0 0 0', fontSize: '0.85em', color: '#00ffff' }}>
                                    （全{totalItems}件の発言）
                                </p>
                            </div>
                        </div>

                        {speakerStats.length > 0 && resultData && (
                            <div style={{
                                padding: '20px',
                                backgroundColor: 'rgba(10, 14, 39, 0.9)',
                                borderRadius: '8px',
                                marginBottom: '16px',
                                border: '2px solid #00ffff'
                            }}>
                                <h3 style={{ marginTop: 0, color: '#00ffff' }}>👥 話者別発言割合</h3>
                                {speakerStats.map(({ speaker, count, percentage }) => {
                                    const barColor = percentage >= 85 ? '#ff4444' : percentage >= 70 ? '#ffaa00' : '#00ff00';
                                    const displayName = speakerNames?.[speaker] || speaker;

                                    return (
                                        <div key={speaker} style={{ marginBottom: '12px' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                                <span style={{ color: '#00ffff', fontSize: '0.9em' }}>{displayName}</span>
                                                <span style={{ color: barColor, fontSize: '0.9em', fontWeight: 'bold' }}>{percentage}%</span>
                                            </div>
                                            <div style={{
                                                width: '100%',
                                                height: '8px',
                                                backgroundColor: 'rgba(0, 0, 0, 0.3)',
                                                borderRadius: '4px',
                                                overflow: 'hidden'
                                            }}>
                                                <div style={{
                                                    width: `${percentage}%`,
                                                    height: '100%',
                                                    backgroundColor: barColor
                                                }} />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        <div style={{
                            padding: '20px',
                            backgroundColor: 'rgba(10, 14, 39, 0.9)',
                            borderRadius: '8px',
                            marginBottom: '16px',
                            border: '2px solid #00ffff'
                        }}>
                            <h3 style={{ marginTop: 0, color: '#00ffff' }}>📝 アジェンダ</h3>
                            <pre style={{
                                whiteSpace: 'pre-wrap',
                                fontSize: '0.95em',
                                lineHeight: '1.6',
                                margin: 0,
                                color: '#00ffff'
                            }}>
                                {agendaText || '（アジェンダなし）'}
                            </pre>
                        </div>

                        {isSuccess ? (
                            <div style={{
                                padding: '16px',
                                backgroundColor: 'rgba(76, 175, 80, 0.2)',
                                borderRadius: '8px',
                                color: '#00ff00',
                                textAlign: 'center',
                                border: '2px solid #00ff00'
                            }}>
                                <strong>素晴らしい！</strong> アジェンダに沿った議論ができました 👏
                            </div>
                        ) : (
                            <div style={{
                                padding: '16px',
                                backgroundColor: 'rgba(255, 152, 0, 0.2)',
                                borderRadius: '8px',
                                color: '#ff9800',
                                textAlign: 'center',
                                border: '2px solid #ff9800'
                            }}>
                                次回はもっとアジェンダに沿った議論を心がけましょう 💪
                            </div>
                        )}
                    </div>
                </section>

                <div style={{ textAlign: 'center' }}>
                    <button
                        type="button"
                        onClick={() => navigate('/poc_satomin')}
                        style={{
                            padding: '12px 32px',
                            fontSize: '1.1em',
                            cursor: 'pointer'
                        }}
                    >
                        新しいミーティングを開始
                    </button>
                </div>
            </div>
        </Layout>
    );
}
