import "./globals.css";

export const metadata = {
  title: "特别想-Lab 员工后台",
  description: "客户线索、客资统计和权限管理"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <div className="shell">
          <aside className="side">
            <div className="brand">
              特别想-Lab
              <br />
              员工后台
            </div>
            <nav className="nav">
              <a href="/">首页</a>
              <a href="/monitoring">数据统计</a>
              <a href="/leads">客户线索</a>
            </nav>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
