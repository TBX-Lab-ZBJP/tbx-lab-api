"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import { intentClassName } from "../lib/intent";
import { Plan, fetchPlans, planLabel } from "../lib/plans";

const ADMIN_API = "/api/admin";

// "all" / "contacted" / "opened" 是固定筛选；其余值为套餐 id（动态）。
type Filter = string;
type FollowupFilter = "all" | "due" | "scheduled" | "none";
type ContactFilter = "all" | "uncontacted";

type Lead = {
  id: string;
  unionid: string;
  product: string;
  name: string;
  phone: string;
  wechat?: string;
  staff_wechat?: string;
  shop: string;
  contact_time: string;
  contacted_at?: string | null;
  opened_at?: string | null;
  intent_level?: string | null;
  followup_note?: string | null;
  next_followup_date?: string | null;
  created_at: string;
};

type User = {
  unionid: string;
  locked_tool: string | null;
  tool_trial_count: number;
  permission?: {
    plan: string;
    status: string;
    expires_at: string | null;
  };
};

// 固定筛选项；套餐相关的筛选项会在组件内按后端套餐动态拼接。
const baseFilters: { id: Filter; label: string }[] = [
  { id: "all", label: "全部客户" },
  { id: "contacted", label: "已联系" },
  { id: "opened", label: "已开通" }
];

const intentFilters = ["全部意向", "未判断", "低意向", "中意向", "高意向", "已成交", "暂不跟进"];

const followupFilters: { id: FollowupFilter; label: string }[] = [
  { id: "all", label: "全部回访" },
  { id: "due", label: "今日待回访" },
  { id: "scheduled", label: "已安排回访" },
  { id: "none", label: "未安排回访" }
];

const toolNames: Record<string, string> = {
  redline: "违禁词话术",
  shop: "门店诊断",
  script: "脚本代写",
  live: "直播话术",
  package: "团购套餐"
};

function toolLabel(tool?: string | null) {
  return tool ? toolNames[tool] || tool : "未选择";
}

function csvCell(value: unknown) {
  return `"${String(value ?? "").replace(/"/g, '""')}"`;
}

function leadDate(lead: Lead) {
  return (lead.created_at || "").slice(0, 10);
}

function todayString() {
  return new Date().toISOString().slice(0, 10);
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [contactFilter, setContactFilter] = useState<ContactFilter>("all");
  const [keyword, setKeyword] = useState("");
  const [intentFilter, setIntentFilter] = useState("全部意向");
  const [followupFilter, setFollowupFilter] = useState<FollowupFilter>("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // 固定筛选 + 每个会员套餐一个筛选项，套餐部分随后端配置自动增减。
  const filters = useMemo<{ id: Filter; label: string }[]>(
    () => [...baseFilters, ...plans.map((plan) => ({ id: plan.id, label: plan.admin_button }))],
    [plans]
  );
  const activeFilterLabel = filters.find((item) => item.id === filter)?.label || "当前";
  const userByUnionid = useMemo(() => new Map(users.map((user) => [user.unionid, user])), [users]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlFilter = params.get("filter");
    const urlIntent = params.get("intent");
    const urlFollowup = params.get("followup") as FollowupFilter | null;
    const urlContact = params.get("contact") as ContactFilter | null;
    if (urlFilter) setFilter(urlFilter);
    if (urlIntent && intentFilters.includes(urlIntent)) setIntentFilter(urlIntent);
    if (urlFollowup && followupFilters.some((item) => item.id === urlFollowup)) setFollowupFilter(urlFollowup);
    if (urlContact === "uncontacted") setContactFilter("uncontacted");
  }, []);

  const filteredLeads = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();
    const today = todayString();
    const planIds = new Set(plans.map((plan) => plan.id));
    return leads.filter((lead) => {
      const user = userByUnionid.get(lead.unionid);
      const date = leadDate(lead);
      const leadIntent = lead.intent_level || "未判断";
      const searchable = [
        lead.name,
        lead.phone,
        lead.wechat,
        lead.staff_wechat,
        lead.shop,
        lead.product,
        lead.contact_time,
        lead.unionid,
        lead.id,
        leadIntent,
        lead.followup_note,
        lead.next_followup_date,
        toolLabel(user?.locked_tool),
        planLabel(plans, user?.permission?.plan)
      ].join(" ").toLowerCase();

      if (filter === "contacted" && !lead.contacted_at) return false;
      if (filter === "opened" && !lead.opened_at) return false;
      if (planIds.has(filter) && !(user?.permission?.status === "active" && user.permission.plan === filter)) return false;
      if (contactFilter === "uncontacted" && lead.contacted_at) return false;
      if (intentFilter !== "全部意向" && leadIntent !== intentFilter) return false;
      if (followupFilter === "due" && !(lead.next_followup_date && lead.next_followup_date <= today)) return false;
      if (followupFilter === "scheduled" && !lead.next_followup_date) return false;
      if (followupFilter === "none" && lead.next_followup_date) return false;
      if (startDate && date < startDate) return false;
      if (endDate && date > endDate) return false;
      if (normalizedKeyword && !searchable.includes(normalizedKeyword)) return false;
      return true;
    });
  }, [contactFilter, endDate, filter, followupFilter, intentFilter, keyword, leads, plans, startDate, userByUnionid]);

  async function refresh() {
    setLoading(true);
    try {
      const [leadRes, userRes] = await Promise.all([
        fetch(`${ADMIN_API}/leads`, { cache: "no-store" }),
        fetch(`${ADMIN_API}/users`, { cache: "no-store" })
      ]);
      setLeads((await leadRes.json()).items || []);
      setUsers((await userRes.json()).items || []);
    } finally {
      setLoading(false);
    }
  }

  async function markLead(leadId: string, action: "contacted" | "opened") {
    await fetch(`${ADMIN_API}/leads/${leadId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    refresh();
  }

  async function grant(unionid: string, plan: string) {
    await fetch(`${ADMIN_API}/permissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unionid, plan })
    });
    refresh();
  }

  function resetSearch() {
    setKeyword("");
    setIntentFilter("全部意向");
    setFollowupFilter("all");
    setContactFilter("all");
    setStartDate("");
    setEndDate("");
  }

  function downloadCsv() {
    const rows = [
      ["姓名", "手机号", "客户微信号", "我们的微信号", "店铺", "咨询项目", "方便沟通时间", "注册/提交日期", "提交时间", "是否已联系", "联系时间", "是否已开通", "开通时间", "意向等级", "下次回访", "跟进备注", "锁定功能", "权限类型", "权限到期"],
      ...filteredLeads.map((lead) => {
        const user = userByUnionid.get(lead.unionid);
        const permission = user?.permission;
        return [
          lead.name,
          lead.phone,
          lead.wechat || "",
          lead.staff_wechat || "TBX-Lab",
          lead.shop,
          lead.product,
          lead.contact_time,
          leadDate(lead),
          lead.created_at,
          lead.contacted_at ? "是" : "否",
          lead.contacted_at || "",
          lead.opened_at ? "是" : "否",
          lead.opened_at || "",
          lead.intent_level || "未判断",
          lead.next_followup_date || "",
          lead.followup_note || "",
          toolLabel(user?.locked_tool),
          permission?.status === "active" ? planLabel(plans, permission.plan) : "未开通",
          permission?.expires_at || ""
        ];
      })
    ];
    const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
    const blob = new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `特别想-Lab-${activeFilterLabel}-客资.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  useEffect(() => {
    refresh();
    fetchPlans().then(setPlans);
  }, []);

  return (
    <div>
      <div className="topline">
        <div>
          <h1>客户线索</h1>
          <p className="muted">按状态、意向、回访日期和关键词快速找到客户，筛选后可下载当前客资表。</p>
        </div>
        <div className="toolbar">
          <button className="btn secondary" onClick={downloadCsv} disabled={filteredLeads.length === 0}>下载{activeFilterLabel}客资</button>
          <button className="btn secondary" onClick={refresh}>{loading ? "刷新中" : "刷新"}</button>
        </div>
      </div>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="filter-row">
          {filters.map((item) => (
            <button className={`filter-btn ${filter === item.id ? "active" : ""}`} key={item.id} onClick={() => setFilter(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        <div className="search-panel lead-search-panel">
          <label className="compact-field wide">
            <span>关键词搜索</span>
            <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜姓名、手机号、店铺、项目、客户ID、备注" />
          </label>
          <label className="compact-field">
            <span>意向等级</span>
            <select value={intentFilter} onChange={(event) => setIntentFilter(event.target.value)}>
              {intentFilters.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="compact-field">
            <span>回访状态</span>
            <select value={followupFilter} onChange={(event) => setFollowupFilter(event.target.value as FollowupFilter)}>
              {followupFilters.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="compact-field">
            <span>注册开始日期</span>
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </label>
          <label className="compact-field">
            <span>注册结束日期</span>
            <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </label>
          <button className="btn secondary" onClick={resetSearch}>清空筛选</button>
        </div>
      </section>

      <section className="card" style={{ marginBottom: 16 }}>
        <h2>客户列表</h2>
        <p className="muted">当前筛选：{filteredLeads.length} 条</p>
        {filteredLeads.length === 0 ? (
          <p className="muted">暂无符合条件的客户。</p>
        ) : (
          <div className="lead-list">
            {filteredLeads.map((lead) => {
              const user = userByUnionid.get(lead.unionid);
              const permission = user?.permission;
              return (
                <div className="lead-row" key={lead.id}>
                  <div>
                    <strong>{lead.name} · {lead.phone}</strong>
                    <p>客户微信号：{lead.wechat || "未填写"}　我们的微信号：{lead.staff_wechat || "TBX-Lab"}</p>
                    <p>咨询项目：{lead.product}</p>
                    <p>店铺：{lead.shop}</p>
                    <p>方便沟通时间：{lead.contact_time}</p>
                    <p>注册/提交日期：{leadDate(lead)}　提交时间：{lead.created_at}</p>
                    <p className="badge-line">
                      <span className={`pill ${lead.contacted_at ? "ok" : ""}`}>{lead.contacted_at ? "已联系" : "未联系"}</span>
                      <span className={`pill ${lead.opened_at ? "ok" : ""}`}>{lead.opened_at ? "已开通" : "未开通"}</span>
                      <span className={`pill intent-pill ${intentClassName(lead.intent_level)}`}>{lead.intent_level || "未判断"}</span>
                      <span className="pill">{toolLabel(user?.locked_tool)}</span>
                      <span className="pill">{permission?.status === "active" ? planLabel(plans, permission.plan) : "无权限"}</span>
                    </p>
                    {lead.next_followup_date ? <p>下次回访：{lead.next_followup_date}</p> : null}
                    {lead.followup_note ? <p className="followup-note">跟进备注：{lead.followup_note}</p> : null}
                  </div>
                  <div className="actions">
                    <Link className="btn secondary" href={`/leads/${encodeURIComponent(lead.unionid)}`}>查看详情</Link>
                    <button className="btn" onClick={() => markLead(lead.id, "contacted")}>标记已联系</button>
                    <button className="btn secondary" onClick={() => markLead(lead.id, "opened")}>标记已开通</button>
                    {plans.map((plan, index) => (
                      <button
                        key={plan.id}
                        className={index === 0 ? "btn" : "btn secondary"}
                        onClick={() => grant(lead.unionid, plan.id)}
                      >
                        {plan.admin_button}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="card">
        <h2>客户权限</h2>
        {users.length === 0 ? (
          <p className="muted">暂无授权客户。</p>
        ) : (
          <div className="table permission-table">
            <div className="table-head">UnionID</div>
            <div className="table-head">锁定功能</div>
            <div className="table-head">试用次数</div>
            <div className="table-head">权限</div>
            <div className="table-head">操作</div>
            {users.map((user) => (
              <Fragment key={user.unionid}>
                <div>{user.unionid}</div>
                <div>{toolLabel(user.locked_tool)}</div>
                <div>{user.tool_trial_count}/3</div>
                <div>{user.permission?.status === "active" ? `${planLabel(plans, user.permission.plan)}，到期 ${user.permission.expires_at}` : "未开通"}</div>
                <div className="table-actions">
                  {plans.map((plan, index) => (
                    <button
                      key={plan.id}
                      className={index === 0 ? "btn" : "btn secondary"}
                      onClick={() => grant(user.unionid, plan.id)}
                    >
                      {plan.admin_button}
                    </button>
                  ))}
                </div>
              </Fragment>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
