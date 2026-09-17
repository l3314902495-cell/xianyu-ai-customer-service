"use client";

import {
  Activity, Bot, Boxes, ChevronLeft, ClipboardList, Database, FlaskConical,
  History, Inbox, LayoutDashboard, MessageSquareText, PackageCheck, PackageSearch,
  PanelLeftClose, Settings2, ShieldAlert, SlidersHorizontal, Wifi,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUI } from "@/lib/store";

const groups = [
  { label: "", items: [{ href: "/", label: "仪表盘", icon: LayoutDashboard }] },
  { label: "客服中心", items: [{ href: "/conversations", label: "在线会话", icon: MessageSquareText }, { href: "/human", label: "待人工处理", icon: Inbox }, { href: "/history", label: "历史会话", icon: History }] },
  { label: "商品中心", items: [{ href: "/products", label: "商品管理", icon: Boxes }, { href: "/knowledge", label: "商品知识库", icon: Database }] },
  { label: "AI 管理", items: [{ href: "/ai/global", label: "全局 AI 设置", icon: Bot }, { href: "/ai/model", label: "模型设置", icon: SlidersHorizontal }, { href: "/ai/rules", label: "回复规则", icon: ShieldAlert }, { href: "/ai/test", label: "AI 测试台", icon: FlaskConical }] },
  { label: "自动化", items: [{ href: "/automation/delivery", label: "自动发货", icon: PackageCheck }] },
  { label: "日志中心", items: [{ href: "/logs/messages", label: "消息日志", icon: ClipboardList }, { href: "/logs/ai", label: "AI 回复日志", icon: Activity }, { href: "/logs/risk", label: "风险日志", icon: ShieldAlert }] },
  { label: "系统设置", items: [{ href: "/accounts", label: "闲鱼账号", icon: Wifi }, { href: "/settings", label: "系统设置", icon: Settings2 }] },
  { label: "开发工具", items: [{ href: "/simulator", label: "闲鱼消息模拟器", icon: PackageSearch }] },
];

export function Sidebar() {
  const path = usePathname();
  const { collapsed, toggle } = useUI();

  return <aside className="app-sidebar flex flex-col" data-collapsed={collapsed} aria-label="主导航">
      <div className="sidebar-brand flex h-16 items-center gap-3 border-b px-4">
        <div className="sidebar-brand-mark">鱼</div>
        <div className="sidebar-copy min-w-0"><b className="sidebar-brand-name block whitespace-nowrap">闲鱼 AI 客服</b><div className="sidebar-brand-caption">SIGNAL DESK</div></div>
      </div>
      <nav className="sidebar-nav flex-1 overflow-y-auto py-4">
        {groups.map((group, index) => <div key={index} className="mb-4">
          {group.label && <div className="sidebar-group-label mb-1 px-5">{group.label}</div>}
          {group.items.map((item) => {
            const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
            const Icon = item.icon;
            return <Link
              title={collapsed ? item.label : undefined}
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`sidebar-link ${active ? "is-active" : ""}`}
            >
              <Icon size={17} aria-hidden="true" /><span className="sidebar-link-label">{item.label}</span>
            </Link>;
          })}
        </div>)}
      </nav>
      <button onClick={toggle} className="sidebar-collapse-button" type="button" aria-label={collapsed ? "展开导航" : "收起导航"}>
        {collapsed ? <ChevronLeft className="rotate-180" size={18} /> : <><PanelLeftClose size={18} /><span className="sidebar-link-label">收起导航</span></>}
      </button>
    </aside>;
}
