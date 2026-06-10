interface Cell {
  label: string;
  value: number;
  count: number;
}

interface Props {
  data: Cell[][];
  rowLabels: string[];
  colLabels: string[];
  title?: string;
  selectedCell?: { row: number; col: number } | null;
  onCellClick?: (row: number, col: number) => void;
}

export default function HeatMap({ data, rowLabels, colLabels, selectedCell, onCellClick }: Props) {
  const allValues = data.flat().map((c) => c.value);
  const maxVal = Math.max(...allValues, 1);
  const minVal = Math.min(...allValues, -1);

  function getCellColor(value: number): string {
    if (value === 0) return 'bg-gray-800';
    if (value > 0) {
      const intensity = Math.min(value / maxVal, 1);
      if (intensity > 0.7) return 'bg-green-600';
      if (intensity > 0.3) return 'bg-green-700/70';
      return 'bg-green-800/50';
    }
    const intensity = Math.min(Math.abs(value) / Math.abs(minVal), 1);
    if (intensity > 0.7) return 'bg-red-600';
    if (intensity > 0.3) return 'bg-red-700/70';
    return 'bg-red-800/50';
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1" />
            {colLabels.map((col) => (
              <th key={col} className="px-2 py-1 text-gray-500 font-normal text-center">{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, ri) => (
            <tr key={ri}>
              <td className="px-2 py-1 text-gray-500 text-right whitespace-nowrap">{rowLabels[ri]}</td>
              {row.map((cell, ci) => {
                const isSelected = selectedCell?.row === ri && selectedCell?.col === ci;
                return (
                  <td key={ci} className="px-1 py-1">
                    <div
                      onClick={() => cell.count > 0 && onCellClick?.(ri, ci)}
                      className={`w-10 h-8 rounded flex items-center justify-center font-medium transition-all ${getCellColor(cell.value)} ${
                        cell.value >= 0 ? 'text-green-200' : 'text-red-200'
                      } ${cell.count > 0 ? 'cursor-pointer hover:ring-1 hover:ring-white/30' : ''} ${
                        isSelected ? 'ring-2 ring-white/60 scale-110' : ''
                      }`}
                      title={`${cell.label}: $${cell.value.toFixed(2)} (${cell.count} trades)`}
                    >
                      {cell.count > 0 ? cell.value.toFixed(0) : ''}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
