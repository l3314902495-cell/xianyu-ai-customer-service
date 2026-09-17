import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: { default: "闲鱼 AI 客服", template: "%s · 闲鱼 AI 客服" },
  description: "稳定、准确、可控的闲鱼 AI 智能客服管理系统",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><Providers>{children}</Providers></body></html>;
}
