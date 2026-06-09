export function InfoTip({ text, className = "" }: { text: string; className?: string }) {
  return (
    <span
      className={`group/tip relative inline-flex align-middle ${className}`}
      tabIndex={0}
      role="note"
      aria-label={text}
    >
      <span className="ml-1 flex h-3.5 w-3.5 cursor-help select-none items-center justify-center rounded-full border border-[var(--color-edge)] text-[9px] font-bold leading-none text-[var(--color-muted)] hover:text-white hover:border-[var(--color-accent)]">
        ?
      </span>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-60 -translate-x-1/2 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-[11px] font-normal normal-case leading-snug tracking-normal text-[#e8edf7] shadow-xl group-hover/tip:block group-focus-within/tip:block"
      >
        {text}
      </span>
    </span>
  );
}
