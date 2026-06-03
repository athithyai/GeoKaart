interface Props {
  size?: number
  className?: string
}

export function LogoIcon({ size = 32, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <rect width="32" height="32" rx="8" fill="#1b3678" />
      <circle cx="16" cy="14" r="6" stroke="#00A1CD" strokeWidth="2" fill="none" />
      <line x1="16" y1="20" x2="16" y2="28" stroke="#00A1CD" strokeWidth="2" strokeLinecap="round" />
      <circle cx="16" cy="14" r="2" fill="#00A1CD" />
    </svg>
  )
}

export function LogoWordmark({ iconSize = 28 }: { iconSize?: number }) {
  return (
    <div className="flex items-center gap-2">
      <LogoIcon size={iconSize} />
      <span className="font-display font-medium text-sm tracking-tight leading-none">
        <span style={{ color: '#1b3678' }}>Geo</span><span style={{ color: '#00A1CD' }}>Kaart</span>
      </span>
    </div>
  )
}
