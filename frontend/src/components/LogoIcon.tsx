interface Props { size?: number; className?: string }

export function LogoIcon({ size = 32, className }: Props) {
  return (
    <svg
      width={size} height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <rect width="32" height="32" rx="8" fill="#1b3678" />
      {/* Pin shape */}
      <circle cx="16" cy="13" r="5.5" stroke="#00A1CD" strokeWidth="2" fill="none" />
      <circle cx="16" cy="13" r="2" fill="#00A1CD" />
      <path d="M16 18.5 C14 21 11 25 11 25" stroke="#00A1CD" strokeWidth="1.5" strokeLinecap="round" opacity="0.4" />
      <path d="M16 18.5 C18 21 21 25 21 25" stroke="#00A1CD" strokeWidth="1.5" strokeLinecap="round" opacity="0.4" />
      <line x1="16" y1="18.5" x2="16" y2="25" stroke="#00A1CD" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function LogoWordmark({ iconSize = 26 }: { iconSize?: number }) {
  return (
    <div className="flex items-center gap-2">
      <LogoIcon size={iconSize} />
      <span className="font-bold text-sm tracking-tight leading-none">
        <span className="text-slate-800 dark:text-slate-100">Geo</span>
        <span style={{ color: '#00A1CD' }}>Kaart</span>
      </span>
    </div>
  )
}
