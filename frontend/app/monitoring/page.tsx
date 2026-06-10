"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BarChart3, CalendarClock, Clock, Flame, PhoneCall, UserCheck, Users } from "lucide-react";
import { intentClassName } from "../lib/intent";

const ADMIN_API = "/api/admin";

type LeadBrief = {
  id: string;
  unionid: string;
  name: string;
  phone: string;
  shop: string;
  product: string;
  intent_level?: string | null;
  next_followup_date?: string | null;
  created_at: string;
};

type Stats = {
  summary: {
    today_leads: number;
    total_leads: number;
    contacted: number;
    opened: number;
    pending: number;
    contact_rate: number;
    open_rate: number;
    video_reviews: number;
    live_reviews: number;
  };
  tool_usage: { id: string; name: string; count: number }[];
  plan_counts?: { id: string; label: string; count: number }[];
  pending_leads: LeadBrief[];
  followup_leads?: LeadBrief[];
  high_intent_leads?: LeadBrief[];
  recent_activities: { id: string; unionid: string; title: string; summary: string; created_at: string }[];
};

const emptyStats: Stats = {
  summary: {
    today_leads: 0,
    total_leads: 0,
    contacted: 0,
    opened: 0,
    pending: 0,
    contact_rate: 0,
    open_rate: 0,
    video_reviews: 0,
    live_reviews: 0
  },
  tool_usage: [],
  plan_counts: [],
  pending_leads: [],
  followup_leads: [],
  high_intent_leads: [],
  recent_activities: []
};

export default function MonitoringPage() {
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const response = await fetch(`${ADMIN_API}/stats`, { cache: "no-store" });
      setStats(await response.json());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const summary = stats.summary;
  const followups = stats.followup_leads || [];
  const highIntentLeads = stats.high_intent_leads || [];
  const mostUsedTool = useMemo(() => [...stats.tool_usage].sort((a, b) => b.count - a.count)[0], [stats.tool_usage]);

  const todayAction = followups.length > 0
    ? `今天优先回访 ${followups.length} 位客户`
    : highIntentLeads.length > 0
      ? `优先推动 ${highIntentLeads.length} 位高意向客户开通`
      : summary.pending > 0
        ? `优先联系 ${summary.pending} 位新客户`
        : "今天暂无积压客户，继续关注新增线索";

  return (
    <>
      <div className="topline">
        <div>
          <h1>数据统计</h1>
          <p className="muted">客户试用、客资跟进、权限开通和复盘使用情况，一页看清。</p>
        </div>
        <div className="toolbar">
          <Link className="btn" href="/leads">去处理客户线索</Link>
          <button className="btn secondary" onClick={refresh}>{loading ? "刷新中" : "刷新数据"}</button>
        </div>
      </div>

      <section className="card action-card" style={{ marginBottom: 16 }}>
        <div>
          <span className="eyebrow">今日动作建议</span>
          <h2>{todayAction}</h2>
          <p className="muted">员工每天先看这里，再进入客户详情页处理具体客户。</p>
        </div>
        <ArrowRight size={28} />
      </section>

      <section className="grid grid-3" style={{ marginBottom: 16 }}>
        <MetricCard icon={<Users size={22} />} value={summary.today_leads} label="今日新增客资" hint={`累计 ${summary.total_leads} 条`} />
        <MetricCard icon={<PhoneCall size={22} />} value={summary.contacted} label="已联系客户" hint={`联系率 ${summary.contact_rate}%`} />
        <MetricCard icon={<UserCheck size={22} />} value={summary.opened} label="已开通客户" hint={`开通率 ${summary.open_rate}%`} />
        <MetricCard icon={<Clock size={22} />} value={summary.pending} label="待联系客户" hint="还没有联系过的客户" tone={summary.pending > 0 ? "warn" : "ok"} />
        <MetricCard icon={<CalendarClock size={22} />} value={followups.length} label="今日待回访" hint="已设置回访日期且到期的客户" tone={followups.length > 0 ? "warn" : "ok"} />
        <MetricCard icon={<Flame size={22} />} value={highIntentLeads.length} label="高意向未开通" hint="优先推动成交或体验" tone={highIntentLeads.length > 0 ? "warn" : "ok"} />
      </section>

      <section className="grid grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h2>转化漏斗</h2>
          <Progress label="联系率" value={summary.contact_rate} />
          <Progress label="开通率" value={summary.open_rate} />
          <div className="mini-grid">
            {(stats.plan_counts || []).map((plan) => (
              <div key={plan.id}><strong>{plan.count}</strong><span>{plan.label}</span></div>
            ))}
            <div><strong>{mostUsedTool?.count || 0}</strong><span>最高功能试用</span></div>
          </div>
        </div>

        <div className="card">
          <h2>功能试用热度</h2>
          {stats.tool_usage.length === 0 ? (
            <p className="muted">暂无功能试用数据。</p>
          ) : (
            <div className="rank-list">
              {stats.tool_usage.map((tool) => (
                <div className="rank-row" key={tool.id}>
                  <span>{tool.name}</span>
                  <strong>{tool.count} 次</strong>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="grid grid-3">
        <LeadQueue title="今日待回访" empty="当前没有到期回访客户。" leads={followups} href="/leads?followup=due" />
        <LeadQueue title="高意向未开通" empty="当前没有高意向未开通客户。" leads={highIntentLeads} href="/leads?intent=高意向&filter=all" />
        <LeadQueue title="新客户待联系" empty="当前没有未联系客户。" leads={stats.pending_leads} href="/leads?filter=all&contact=uncontacted" />
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2><BarChart3 size={20} /> 最近动态</h2>
        {stats.recent_activities.length === 0 ? (
          <p className="muted">暂无客户使用记录。客户试用功能、使用复盘或员工开通权限后，会出现在这里。</p>
        ) : (
          <div className="timeline">
            {stats.recent_activities.map((activity) => (
              <div className="timeline-item" key={activity.id}>
                <strong>{activity.title}</strong>
                <p>{activity.summary}</p>
                <p>{activity.created_at}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function LeadQueue({ title, empty, leads, href }: { title: string; empty: string; leads: LeadBrief[]; href: string }) {
  return (
    <div className="card task-card">
      <div className="section-title-row">
        <h2>{title}</h2>
        <Link className="text-link" href={href}>查看全部</Link>
      </div>
      {leads.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <div className="timeline">
          {leads.map((lead) => (
            <div className="timeline-item" key={lead.id}>
              <strong>{lead.name} · {lead.phone}</strong>
              <p>{lead.shop} · {lead.product}</p>
              <p>意向等级：<span className={`pill intent-pill ${intentClassName(lead.intent_level)}`}>{lead.intent_level || "未判断"}</span></p>
              {lead.next_followup_date ? <p>回访日期：{lead.next_followup_date}</p> : null}
              <Link className="text-link" href={`/leads/${encodeURIComponent(lead.unionid)}`}>查看客户详情</Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricCard({
  icon,
  value,
  label,
  hint,
  tone
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
  hint: string;
  tone?: "warn" | "ok";
}) {
  return (
    <div className={`card stat-card ${tone ? `tone-${tone}` : ""}`}>
      {icon}
      <div className="metric">{value}</div>
      <div className="metric-label">{label}</div>
      <div className="muted">{hint}</div>
    </div>
  );
}

function Progress({ label, value }: { label: string; value: number }) {
  return (
    <>
      <div className="progress-row">
        <span>{label}</span>
        <strong>{value}%</strong>
      </div>
      <div className="progress-bar"><span style={{ width: `${Math.min(value, 100)}%` }} /></div>
    </>
  );
}
