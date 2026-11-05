import { formatDateKey } from "@/lib/format";

export function DayNavigator({
  dayKey,
  dayIndex,
  dayCount,
  onFirst,
  onPrevious,
  onNext,
  noun = "day",
}: {
  dayKey: string | null;
  dayIndex: number;
  dayCount: number;
  onFirst: () => void;
  onPrevious: () => void;
  onNext: () => void;
  noun?: string;
}) {
  return (
    <div className="day-nav" aria-label={`${noun} navigation`}>
      <span className="day-nav__status">
        <span className="day-nav__label">{formatDateKey(dayKey)}</span>
        <span>
          {dayCount === 0 ? `no ${noun}s` : `${dayIndex + 1} / ${dayCount}`}
        </span>
      </span>
      <div className="day-nav__actions">
        <button type="button" className="button" onClick={onFirst} disabled={dayIndex === 0}>
          Back to front
        </button>
        <button
          type="button"
          className="button"
          onClick={onPrevious}
          disabled={dayCount === 0 || dayIndex >= dayCount - 1}
        >
          Previous day
        </button>
        <button
          type="button"
          className="button"
          onClick={onNext}
          disabled={dayCount === 0 || dayIndex === 0}
        >
          Next day
        </button>
      </div>
    </div>
  );
}
