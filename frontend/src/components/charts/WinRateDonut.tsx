interface Props {
  wins: number;
  losses: number;
  size?: number;
}

export default function WinRateDonut({ wins, losses, size = 120 }: Props) {
  const total = wins + losses;
  const winRate = total > 0 ? (wins / total) * 100 : 0;
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const winArc = (winRate / 100) * circumference;
  const center = size / 2;

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#374151"
          strokeWidth={8}
        />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#22C55E"
          strokeWidth={8}
          strokeDasharray={`${winArc} ${circumference}`}
          strokeLinecap="round"
        />
      </svg>
      <div className="text-center -mt-[76px] mb-8">
        <p className="text-xl font-bold text-white">{winRate.toFixed(1)}%</p>
        <p className="text-xs text-gray-500">{wins}W / {losses}L</p>
      </div>
    </div>
  );
}
