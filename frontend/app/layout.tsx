import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AURA-EVAL — Autonomous AI Evaluation Infrastructure',
  description:
    'Generate. Critique. Refine. Validate. Build reliable AI datasets automatically with an autonomous multi-agent evaluation pipeline.',
  applicationName: 'AURA-EVAL',
  openGraph: {
    title: 'AURA-EVAL — Autonomous AI Evaluation Infrastructure',
    description: 'Multi-agent generation, evaluation, refinement and dataset building with full observability.',
    type: 'website',
  },
};

export const viewport: Viewport = { themeColor: '#07090d' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">{children}</body>
    </html>
  );
}
