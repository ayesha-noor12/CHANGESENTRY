import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ChangeSentry",
  description: "Detect what a code change could break before it reaches production.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
