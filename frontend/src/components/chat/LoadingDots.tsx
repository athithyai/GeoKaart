/** Animated 3-dot loading indicator. */
export function LoadingDots() {
  return (
    <div className="flex items-center gap-1 px-1" aria-label="Loading…">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-gray-400 dark:bg-gray-500 inline-block"
          style={{
            animation: `dotBounce 1.2s ease-in-out ${i * 0.15}s infinite`,
          }}
        />
      ))}
    </div>
  )
}
