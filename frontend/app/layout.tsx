import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ariadne",
  description: "Ask questions about a codebase. Every answer cites the exact lines it came from.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
