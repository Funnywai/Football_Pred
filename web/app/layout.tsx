import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Touchline/Lab — Paper Football Research Terminal",
  description:
    "Read-only paper-trading dashboard for football model probabilities, bet decisions, calibration and ledger accounting.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to dashboard content
        </a>
        {children}
      </body>
    </html>
  );
}
