"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { intentClassName } from "../../lib/intent";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

type Lead = {
  id: string;
  product: string;
  name: string;
  phone: string;
  wechat?: string;
  staff_wechat?: string;
  shop: string;
  contact_time: string;
  status: string;
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
  tool_trials_remaining: number;
  review_used: { video: boolean; live: boolean };
  permission?: { plan: string; status: string; expires_at: string | null };
};

type Activity = {
  id: string;
  type: string;
  title: string;
  summary: string;
  created_at: string;
};

const intentOptions = ["未判断", "低意向", "中意向", "高意向", "已成交", "暂不跟进"];

const noteTemplates = [
  "已加企微，客户希望先了解门店诊断，约明天二次沟通。",
  "客户对价格有顾虑，需要补充案例和使用效果。",
  "客户更关心直播话术和团购套餐，建议下次重点讲这两块。",
  "客户暂时不方便沟通，已约 3 天后回访。",
  "客户已成交，需确认权限开通和首次使用情况。"
];

function planLabel(plan?: string) {
  if (plan === "trial_7") return "7 天体验权限";
  if (plan === "full_365") return "365 天全功能权限";
  return "未开通";
}

function toolLabel(tool?: string | null) {
  const labels: Record<string, string> = {
    redline: "违禁词话术",
    shop: "门店诊断",
    script: "脚本代写",
    live: "直播话术",
    package: "团购套餐"
  };
  return tool ? labels[tool] || tool : "未选择";
}

function dateAfter(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function followupAdvice(intent: string) {
  if (intent === "高意向") return "建议今天优先跟进，直接确认购买路径、开通周期和使用场景。";
  if (intent === "中意向") return "建议 1-2 天内回访，重点解决顾虑，并补充案例或使用效果。";
  if (intent === "低意向") return "建议 3-7 天后轻触达，先发一个低门槛体验或诊断入口。";
  if (intent === "已成交") return "建议确认权限是否开通，并记录首次使用反馈。";
  if (intent === "暂不跟进") return "建议写清楚原因，避免后续员工重复打扰。";
  return "建议先完成第一次联系，再判断客户意向等级。";
}

function buildFollowupScript(lead: Lead, intent: string, user: User | null) {
  const shop = lead.shop || "您的门店";
  const product = lead.product || "本地生活智能员工";
  const permissionText = user?.permission?.status === "active"
    ? `您现在已经开通了${planLabel(user.permission.plan)}，我这边可以帮您确认一下怎么用更顺手。`
    : "您这边如果想继续完整使用，我可以帮您登记并安排开通。";

  if (intent === "高意向") {
    return `您好，我是特别想-Lab 的工作人员。刚看到您提交了${product}的咨询，店铺是${shop}。\n\n您这类情况建议先把当前最急的一个问题跑通，比如门店诊断、直播话术或短视频复盘。${permissionText}\n\n我想和您确认 3 个信息：\n1. 现在最想先解决到店、团购还是直播成交？\n2. 您方便让我们看一条近期内容或一场直播数据吗？\n3. 如果今天给您开通，您这边谁来试用？`;
  }
  if (intent === "中意向") {
    return `您好，我是特别想-Lab 的工作人员。看到您咨询了${product}，我先简单跟您同步一下。\n\n这个工具主要是给本地生活商家做免费试用、复盘和经营建议辅助，不会自动发布，也不会替代员工判断。\n\n您可以先告诉我：\n1. ${shop}现在主要做餐饮、酒旅还是综合本地生活？\n2. 最近最卡的是内容、直播、团购套餐还是门店转化？\n3. 您希望我们先帮您看哪一块？`;
  }
  if (intent === "低意向") {
    return `您好，我是特别想-Lab 的工作人员。您之前提交过${product}咨询，我这边不打扰您太久。\n\n如果您现在还不确定要不要用，可以先做一次轻量诊断：告诉我店铺类型和目前最头疼的问题，我帮您判断先从内容、套餐还是直播入手。\n\n方便的时候您回复一句“诊断”，我再继续跟您对接。`;
  }
  if (intent === "已成交") {
    return `您好，您这边的权限我再确认一下。${permissionText}\n\n建议您第一次使用先跑一个最明确的场景，不要五个功能一起试：\n1. 先选一个当前最急的问题\n2. 按页面提示补充门店情况\n3. 把结果发我，我们帮您判断下一步怎么改`;
  }
  if (intent === "暂不跟进") {
    return `您好，我是特别想-Lab 的工作人员。之前您提交过${product}咨询，如果近期暂时不需要，我们这边先不频繁打扰。\n\n后续如果您想做门店诊断、短视频复盘、直播话术或团购套餐优化，可以再联系我。`;
  }
  return `您好，我是特别想-Lab 的工作人员。看到您提交了${product}咨询，店铺是${shop}。\n\n我先和您确认一下需求：您现在最想解决的是门店到店、短视频内容、直播成交，还是团购套餐设计？您简单说一下情况，我这边帮您判断适合先试哪个功能。`;
}

export default function LeadDetailPage({ params }: { params: { unionid: string } }) {
  const unionid = decodeURIComponent(params.unionid);
  const [user, setUser] = useState<User | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [intentLevel, setIntentLevel] = useState("未判断");
  const [nextFollowupDate, setNextFollowupDate] = useState("");
  const [followupNote, setFollowupNote] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const response = await fetch(`${API}/api/v1/wechat-mp/admin/users/${encodeURIComponent(unionid)}/activity`, {
        cache: "no-store"
      });
      const data = await response.json();
      const leadItems = data.leads || [];
      setUser(data.user);
      setLeads(leadItems);
      setActivities(data.activities || []);
      if (leadItems[0]) {
        setIntentLevel(leadItems[0].intent_level || "未判断");
        setNextFollowupDate(leadItems[0].next_followup_date || "");
        setFollowupNote(leadItems[0].followup_note || "");
      }
    } finally {
      setLoading(false);
    }
  }

  async function markLead(leadId: string, action: "contacted" | "opened") {
    await fetch(`${API}/api/v1/wechat-mp/admin/leads/${leadId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    refresh();
  }

  async function grant(plan: "trial_7" | "full_365") {
    await fetch(`${API}/api/v1/wechat-mp/admin/permissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unionid, plan })
    });
    refresh();
  }

  async function saveFollowup(leadId: string) {
    setSaving(true);
    try {
      await fetch(`${API}/api/v1/wechat-mp/admin/leads/${leadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intent_level: intentLevel,
          next_followup_date: nextFollowupDate,
          followup_note: followupNote
        })
      });
      await refresh();
    } finally {
      setSaving(false);
    }
  }

  async function copyScript(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  function applyNoteTemplate(template: string) {
    setFollowupNote((current) => current ? `${current}\n${template}` : template);
  }

  useEffect(() => {
    refresh();
  }, []);

  const latestLead = leads[0];
  const followupScript = useMemo(() => {
    return latestLead ? buildFollowupScript(latestLead, intentLevel, user) : "";
  }, [intentLevel, latestLead, user]);

  return (
    <>
      <div className="topline">
        <div>
          <Link className="text-link" href="/leads">返回客户线索</Link>
          <h1>客户详情</h1>
          <p className="muted">员工在这里完成客户跟进、权限开通、回访记录和跟进话术准备。</p>
        </div>
        <div className="toolbar">
          <button className="btn secondary" onClick={refresh}>{loading ? "刷新中" : "刷新"}</button>
        </div>
      </div>

      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <section className="card">
          <h2>客户资料</h2>
          {latestLead ? (
            <>
              <p><strong>{latestLead.name}</strong> · {latestLead.phone}</p>
              <p>客户微信号：{latestLead.wechat || "未填写"}</p>
              <p>我们的微信号：{latestLead.staff_wechat || "TBX-Lab"}</p>
              <p>店铺：{latestLead.shop}</p>
              <p>咨询项目：{latestLead.product}</p>
              <p>方便沟通时间：{latestLead.contact_time}</p>
              <p>提交时间：{latestLead.created_at}</p>
              <p className="badge-line">
                <span className={`pill ${latestLead.contacted_at ? "ok" : ""}`}>{latestLead.contacted_at ? "已联系" : "未联系"}</span>
                <span className={`pill ${latestLead.opened_at ? "ok" : ""}`}>{latestLead.opened_at ? "已开通" : "未开通"}</span>
                <span className={`pill intent-pill ${intentClassName(latestLead.intent_level)}`}>{latestLead.intent_level || "未判断"}</span>
              </p>
            </>
          ) : (
            <p className="muted">暂无线索资料。</p>
          )}
        </section>

        <section className="card">
          <h2>当前权益</h2>
          {user ? (
            <>
              <p>锁定功能：{toolLabel(user.locked_tool)}</p>
              <p>功能试用：{user.tool_trial_count}/3，剩余 {user.tool_trials_remaining} 次</p>
              <p>短视频复盘：{user.review_used.video ? "已使用" : "未使用"}</p>
              <p>直播复盘：{user.review_used.live ? "已使用" : "未使用"}</p>
              <p>权限：{user.permission?.status === "active" ? `${planLabel(user.permission.plan)}，到期 ${user.permission.expires_at}` : "未开通"}</p>
            </>
          ) : (
            <p className="muted">加载中。</p>
          )}
        </section>
      </div>

      {latestLead && (
        <section className="card" style={{ marginBottom: 16 }}>
          <h2>快捷处理</h2>
          <p className="muted">员工常用动作放在这里，避免反复回到列表页。</p>
          <div className="quick-actions">
            <button className="btn" onClick={() => markLead(latestLead.id, "contacted")}>标记已联系</button>
            <button className="btn secondary" onClick={() => markLead(latestLead.id, "opened")}>标记已开通</button>
            <button className="btn" onClick={() => grant("trial_7")}>开通 7 天</button>
            <button className="btn secondary" onClick={() => grant("full_365")}>开通 365 天</button>
          </div>
        </section>
      )}

      {latestLead && (
        <section className="card" style={{ marginBottom: 16 }}>
          <h2>员工跟进</h2>
          <p className="muted">保存后，数据统计页和客户线索页都会同步更新。</p>
          <div className="advice-box">{followupAdvice(intentLevel)}</div>
          <div className="followup-form">
            <label className="field">
              <span>客户意向等级</span>
              <select value={intentLevel} onChange={(event) => setIntentLevel(event.target.value)}>
                {intentOptions.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>下次回访日期</span>
              <input type="date" value={nextFollowupDate} onChange={(event) => setNextFollowupDate(event.target.value)} />
            </label>
            <div className="quick-date-row">
              <button type="button" className="filter-btn" onClick={() => setNextFollowupDate(dateAfter(1))}>明天回访</button>
              <button type="button" className="filter-btn" onClick={() => setNextFollowupDate(dateAfter(3))}>3 天后</button>
              <button type="button" className="filter-btn" onClick={() => setNextFollowupDate(dateAfter(7))}>7 天后</button>
              <button type="button" className="filter-btn" onClick={() => setNextFollowupDate("")}>清空回访</button>
            </div>
            <div className="note-template-row">
              {noteTemplates.map((template) => (
                <button className="filter-btn" key={template} type="button" onClick={() => applyNoteTemplate(template)}>
                  {template}
                </button>
              ))}
            </div>
            <label className="field full">
              <span>跟进备注</span>
              <textarea
                value={followupNote}
                onChange={(event) => setFollowupNote(event.target.value)}
                placeholder="例如：已加企微，客户想了解餐饮门店诊断，约明天下午二次沟通。"
              />
            </label>
          </div>
          <button className="btn" onClick={() => saveFollowup(latestLead.id)} disabled={saving}>
            {saving ? "保存中" : "保存跟进信息"}
          </button>
        </section>
      )}

      {latestLead && (
        <section className="card" style={{ marginBottom: 16 }}>
          <div className="section-title-row">
            <div>
              <h2>跟进话术</h2>
              <p className="muted">员工可复制后通过企微或电话人工跟进。话术会根据当前意向等级变化。</p>
            </div>
            <button className="btn" onClick={() => copyScript(followupScript)}>
              {copied ? "已复制" : "复制话术"}
            </button>
          </div>
          <pre className="script-box">{followupScript}</pre>
        </section>
      )}

      <section className="card" style={{ marginBottom: 16 }}>
        <h2>线索记录</h2>
        {leads.length === 0 ? (
          <p className="muted">暂无线索记录。</p>
        ) : (
          <div className="timeline">
            {leads.map((lead) => (
              <div className="timeline-item" key={lead.id}>
                <strong>{lead.product}</strong>
                <p>{lead.created_at}</p>
                <p>{lead.name} · {lead.phone} · 微信号：{lead.wechat || "未填写"} · {lead.shop}</p>
                <p>我们的微信号：{lead.staff_wechat || "TBX-Lab"}</p>
                <p>方便沟通时间：{lead.contact_time}</p>
                <p>意向等级：<span className={`pill intent-pill ${intentClassName(lead.intent_level)}`}>{lead.intent_level || "未判断"}</span></p>
                {lead.next_followup_date ? <p>下次回访：{lead.next_followup_date}</p> : null}
                {lead.followup_note ? <p className="followup-note">跟进备注：{lead.followup_note}</p> : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h2>使用记录</h2>
        {activities.length === 0 ? (
          <p className="muted">暂无使用记录。</p>
        ) : (
          <div className="timeline">
            {activities.map((activity) => (
              <div className="timeline-item" key={activity.id}>
                <strong>{activity.title}</strong>
                <p>{activity.created_at}</p>
                <p>{activity.summary}</p>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
