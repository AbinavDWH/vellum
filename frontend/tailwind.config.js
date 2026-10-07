/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        base: "var(--bg-base)",
        surface: "var(--bg-surface)",
        elevated: "var(--bg-elevated)",

        nav: {
          DEFAULT: "var(--nav-bg)",
          hover: "var(--nav-hover, var(--bg-elevated))",
          active: "var(--brand-dim)",
          border: "var(--line)",
          section: "var(--nav-section, var(--ink-tertiary))",
          icon: "var(--ink-tertiary)",
          'icon-active': "var(--brand-text, var(--brand))",
          indicator: "var(--brand)",
        },

        line: {
          DEFAULT: "var(--line)",
          strong: "var(--line-strong, var(--line))",
        },
        badge: "var(--badge-bg, var(--bg-surface))",
        selection: "var(--selection)",

        ink: {
          primary: "var(--ink-primary)",
          secondary: "var(--ink-secondary)",
          tertiary: "var(--ink-tertiary)",
        },

        brand: {
          DEFAULT: "var(--brand)",
          hover: "var(--brand-hover, var(--brand))",
          ink: "var(--brand-ink)",
          text: "var(--brand-text, var(--brand))",
          dim: "var(--brand-dim)",
        },

        ok: "var(--risk-low, var(--ok))",
        warn: "var(--risk-medium, var(--warn))",
        high: "var(--risk-high, var(--high))",
        crit: "var(--risk-critical, var(--crit))",
        'risk-low': "var(--risk-low, var(--ok))",
        'risk-medium': "var(--risk-medium, var(--warn))",
        'risk-high': "var(--risk-high, var(--high))",
        'risk-critical': "var(--risk-critical, var(--crit))",
        'risk-low-dim': "var(--risk-low-dim)",
        'risk-medium-dim': "var(--risk-medium-dim)",
        'risk-high-dim': "var(--risk-high-dim)",
        'risk-critical-dim': "var(--risk-critical-dim)",

        code: {
          keyword: "var(--code-keyword)",
          string: "var(--code-string)",
          number: "var(--code-number)",
          comment: "var(--code-comment)",
          fn: "var(--code-fn)",
          punct: "var(--code-punct)",
        },

        info: "var(--info, var(--brand-text, var(--brand)))",
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '8px',
        md: '8px',
        lg: '8px',
        xl: '12px',
        '2xl': '16px',
        full: '999px',
      },
      boxShadow: {
        'drawer': '-10px 0 30px -5px rgba(0, 0, 0, 0.4)',
        'modal': '0 20px 50px -12px rgba(0, 0, 0, 0.5)',
      },
      transitionDuration: {
        150: '150ms',
        200: '200ms',
      },
    },
  },
  plugins: [],
}
