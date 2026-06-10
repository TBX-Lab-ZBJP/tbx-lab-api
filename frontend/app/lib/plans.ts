// 会员套餐 —— 员工后台统一从这里读取套餐数据。
// 套餐的唯一数据源是后端 backend/app/api/mp.py 里的 PLANS 配置；
// 后端改了套餐，这里和所有用到的页面（客户线索、客户详情、数据统计）会自动跟着变。

const ADMIN_API = "/api/admin";

export type Plan = {
  id: string;
  days: number;
  label: string;
  admin_button: string;
  summary_label: string;
  price: number;
  upgrade_label: string;
  show_in_miniapp: boolean;
};

// 拉取后端会员套餐列表。网络异常时返回空数组，页面降级但不报错。
export async function fetchPlans(): Promise<Plan[]> {
  try {
    const response = await fetch(`${ADMIN_API}/plans`, { cache: "no-store" });
    if (!response.ok) return [];
    const data = await response.json();
    return (data.items || []) as Plan[];
  } catch {
    return [];
  }
}

// 根据套餐 id 取显示名称。未开通或套餐不存在时回退为「未开通」。
export function planLabel(plans: Plan[], planId?: string | null): string {
  if (!planId) return "未开通";
  const plan = plans.find((item) => item.id === planId);
  return plan ? plan.label : "未开通";
}
