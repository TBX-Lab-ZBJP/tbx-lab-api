import Link from "next/link";
import { BarChart3, KeyRound, UserRoundCheck } from "lucide-react";

export default function Home() {
  return (
    <>
      <div className="topline">
        <div>
          <h1>特别想-Lab 本地生活智能员工后台</h1>
          <p className="muted">这个后台用于客户免费试用、复盘记录、客资跟进和权限开通。</p>
        </div>
        <span className="pill">v1.0 · 员工内部使用</span>
      </div>

      <section className="grid grid-3">
        <div className="card stat-card">
          <UserRoundCheck size={24} />
          <div className="metric">客资</div>
          <div className="muted">查看客户提交的联系方式，并标记联系、开通和跟进状态。</div>
        </div>
        <div className="card stat-card">
          <KeyRound size={24} />
          <div className="metric">权限</div>
          <div className="muted">人工开通 7 天体验权限或 365 天全功能权限。</div>
        </div>
        <div className="card stat-card">
          <BarChart3 size={24} />
          <div className="metric">统计</div>
          <div className="muted">查看试用、复盘、联系率、开通率和待回访客户。</div>
        </div>
      </section>

      <section className="card work-card">
        <h2>今日工作入口</h2>
        <div className="work-steps">
          <p>1. 先进入客户线索，查看新提交客户。</p>
          <p>2. 按实际沟通情况标记已联系，并填写意向等级和下次回访时间。</p>
          <p>3. 对成交或体验客户人工开通 7 天 / 365 天权限。</p>
          <p>4. 在数据统计里查看待回访客户和转化情况。</p>
        </div>
        <div className="toolbar" style={{ marginTop: 18 }}>
          <Link className="btn" href="/leads">进入客户线索</Link>
          <Link className="btn secondary" href="/monitoring">查看数据统计</Link>
        </div>
      </section>
    </>
  );
}
