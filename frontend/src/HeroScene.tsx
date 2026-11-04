// 히어로 일러스트 (바다·등대·지도·캐리어·이정표). 순수 SVG 라 추가 에셋 없이 동작한다.
export default function HeroScene() {
  return (
    <svg viewBox="0 0 640 520" className="scene" role="img" aria-label="여행 일러스트">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#dff1ff" />
          <stop offset="1" stopColor="#9fd6f3" />
        </linearGradient>
        <linearGradient id="sea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#7fcbe9" />
          <stop offset="1" stopColor="#4fb3df" />
        </linearGradient>
        <linearGradient id="sand" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffe6a8" />
          <stop offset="1" stopColor="#ffd37a" />
        </linearGradient>
        <linearGradient id="case" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffd84f" />
          <stop offset="1" stopColor="#f5b62a" />
        </linearGradient>
        <clipPath id="blob">
          <path d="M60 230C40 120 150 40 290 60c90 12 150-40 240 0 70 30 110 110 90 210-15 80-70 150-200 160S80 420 60 230z" />
        </clipPath>
      </defs>

      {/* 하늘·바다·모래 블롭 */}
      <g clipPath="url(#blob)">
        <rect width="640" height="520" fill="url(#sky)" />
        <circle cx="520" cy="110" r="46" fill="#ffd166" opacity="0.9" />
        <ellipse cx="300" cy="300" rx="400" ry="90" fill="url(#sea)" />
        <path d="M0 320c90-24 180-24 270 0s180 24 270 0 100-10 160 0v220H0z" fill="url(#sand)" />
        {/* 산·섬·등대 */}
        <path d="M150 300c40-70 100-90 150-20 30-40 60-50 100 20z" fill="#7ccf8d" />
        <path d="M220 300c30-45 70-60 110-10z" fill="#5fbf73" opacity="0.8" />
        <g transform="translate(360 230)">
          <ellipse cx="0" cy="72" rx="42" ry="10" fill="#f9e6a5" />
          <path d="M-9 72 -5 20h10l4 52z" fill="#fff" />
          <path d="M-7 36h14v8H-7zM-6 52h12v8H-6z" fill="#ff6b4a" />
          <rect x="-8" y="12" width="16" height="10" rx="2" fill="#ff6b4a" />
          <circle cx="0" cy="16" r="3" fill="#ffe08a" />
        </g>
        {/* 구름 */}
        <Cloud x={120} y={120} s={1} />
        <Cloud x={410} y={60} s={0.7} />
        {/* 파도 */}
        <path d="M60 260q30-10 60 0t60 0" stroke="#fff" strokeWidth="4" fill="none" opacity="0.7" strokeLinecap="round" />
        <path d="M400 275q30-10 60 0t60 0" stroke="#fff" strokeWidth="4" fill="none" opacity="0.7" strokeLinecap="round" />
      </g>

      {/* 비행기 + 점선 */}
      <path d="M300 95c60-40 120-40 190 10" stroke="#fff" strokeWidth="3" strokeDasharray="8 10" fill="none" strokeLinecap="round" />
      <g transform="translate(250 100) rotate(-18)">
        <path d="M0 0h70l18 8-18 8H0l-10-8z" fill="#fff" stroke="#e9eef5" strokeWidth="2" />
        <path d="M20 0 40-18h12L36 0zM20 16l20 18h12L36 16z" fill="#ff6b4a" />
        <circle cx="52" cy="8" r="3" fill="#8fd3f4" />
        <circle cx="40" cy="8" r="3" fill="#8fd3f4" />
      </g>

      {/* 지도 */}
      <g transform="translate(120 340)">
        <path d="M0 40 80 10l80 30 80-30 80 30 80-30v120l-80 30-80-30-80 30-80-30-80 30z" fill="#fff" stroke="#f0e4d6" strokeWidth="3" />
        <path d="M30 70q60-40 120 0t120 0t110-10" stroke="#8fd3f4" strokeWidth="18" fill="none" strokeLinecap="round" opacity="0.8" />
        <path d="M20 110q40-30 90 0t90 0t110-20" stroke="#8ad28c" strokeWidth="12" fill="none" strokeLinecap="round" opacity="0.8" />
        <path d="M60 30c0 20 60 40 60 90" stroke="#ff6b4a" strokeWidth="4" strokeDasharray="6 8" fill="none" strokeLinecap="round" />
      </g>

      {/* 캐리어 */}
      <g transform="translate(330 250)">
        <rect x="32" y="-22" width="36" height="30" rx="8" fill="none" stroke="#5c4b3b" strokeWidth="8" />
        <rect x="0" y="0" width="100" height="130" rx="16" fill="url(#case)" />
        <rect x="0" y="36" width="100" height="10" fill="#e39f1b" opacity="0.6" />
        <rect x="0" y="84" width="100" height="10" fill="#e39f1b" opacity="0.6" />
        <rect x="38" y="52" width="24" height="26" rx="6" fill="#fff" opacity="0.9" />
        <circle cx="20" cy="138" r="8" fill="#5c4b3b" />
        <circle cx="80" cy="138" r="8" fill="#5c4b3b" />
      </g>

      {/* 큰 핀 */}
      <g transform="translate(270 220)">
        <ellipse cx="0" cy="120" rx="28" ry="8" fill="#e8a57a" opacity="0.45" />
        <path d="M0 0C-33 0-60 26-60 58c0 42 50 56 60 62 10-6 60-20 60-62C60 26 33 0 0 0z" fill="#ff6b4a" />
        <path d="M0 0C-33 0-60 26-60 58c0 10 3 18 7 26C-50 44-30 20 0 20s50 24 53 64c4-8 7-16 7-26C60 26 33 0 0 0z" fill="#ff8a6f" />
        <circle cx="0" cy="54" r="22" fill="#fff" />
      </g>

      {/* 카메라 */}
      <g transform="translate(455 380)">
        <rect x="0" y="10" width="86" height="58" rx="14" fill="#fff" stroke="#f0e4d6" strokeWidth="3" />
        <rect x="24" y="0" width="30" height="16" rx="6" fill="#ffb199" />
        <circle cx="43" cy="40" r="18" fill="#3c3b45" />
        <circle cx="43" cy="40" r="10" fill="#8fd3f4" />
        <circle cx="47" cy="36" r="3" fill="#fff" />
        <circle cx="72" cy="24" r="4" fill="#ff6b4a" />
      </g>

      {/* 이정표 */}
      <g transform="translate(540 150)">
        <rect x="-7" y="0" width="14" height="300" rx="6" fill="#b7865a" />
        <Sign y={10} rot={-6} label="여행 코스" />
        <Sign y={80} rot={5} label="맛집·카페" />
        <Sign y={150} rot={-4} label="관광지" />
        <Sign y={220} rot={6} label="주차장 찾기" />
      </g>
    </svg>
  )
}

function Cloud({ x, y, s }: { x: number; y: number; s: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`} fill="#fff" opacity="0.95">
      <ellipse cx="0" cy="0" rx="46" ry="22" />
      <circle cx="-18" cy="-10" r="20" />
      <circle cx="14" cy="-16" r="26" />
    </g>
  )
}

function Sign({ y, rot, label }: { y: number; rot: number; label: string }) {
  return (
    <g transform={`translate(0 ${y}) rotate(${rot})`}>
      <path d="M-78 0h120l16 20-16 20H-78z" fill="#ffd9a3" stroke="#e5b56b" strokeWidth="3" />
      <text x="-16" y="26" textAnchor="middle" fontSize="18" fontWeight="700" fill="#5c4b3b" fontFamily="inherit">
        {label}
      </text>
    </g>
  )
}
