import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        border: 'var(--border)',
        input: 'var(--input)',
        ring: 'var(--ring)',
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        primary: {
          DEFAULT: 'var(--primary)',
          foreground: 'var(--primary-foreground)',
        },
        secondary: {
          DEFAULT: 'var(--secondary)',
          foreground: 'var(--secondary-foreground)',
        },
        destructive: {
          DEFAULT: 'var(--destructive)',
          foreground: 'var(--destructive-foreground)',
        },
        muted: {
          DEFAULT: 'var(--muted)',
          foreground: 'var(--muted-foreground)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          foreground: 'var(--accent-foreground)',
        },
        popover: {
          DEFAULT: 'var(--card)',
          foreground: 'var(--card-foreground)',
        },
        card: {
          DEFAULT: 'var(--card)',
          foreground: 'var(--card-foreground)',
        },
        verdict: {
          pass: 'var(--verdict-pass)',
          'pass-muted': 'var(--verdict-pass-muted)',
          'app-fail': 'var(--verdict-app-fail)',
          'app-fail-muted': 'var(--verdict-app-fail-muted)',
          harness: 'var(--verdict-harness)',
          'harness-muted': 'var(--verdict-harness-muted)',
          blocked: 'var(--verdict-blocked)',
          'blocked-muted': 'var(--verdict-blocked-muted)',
          'not-run': 'var(--verdict-not-run)',
          'not-run-muted': 'var(--verdict-not-run-muted)',
          running: 'var(--verdict-running)',
          'running-muted': 'var(--verdict-running-muted)',
          waiting: 'var(--verdict-waiting)',
          'waiting-muted': 'var(--verdict-waiting-muted)',
        },
        actor: {
          laya: 'var(--actor-laya)',
          'laya-muted': 'var(--actor-laya-muted)',
          pilot: 'var(--actor-pilot)',
          'pilot-muted': 'var(--actor-pilot-muted)',
          orchestrator: 'var(--actor-orchestrator)',
          'orchestrator-muted': 'var(--actor-orchestrator-muted)',
          person: 'var(--actor-person)',
          'person-muted': 'var(--actor-person-muted)',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
    },
  },
  plugins: [],
}

export default config
