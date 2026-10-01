const STEPS = [
  { num: 1, title: "上传数据", desc: "Excel / CSV" },
  { num: 2, title: "自动识别", desc: "字段映射" },
  { num: 3, title: "批量分析", desc: "客户池诊断" },
  { num: 4, title: "生成周报", desc: "图表与 SOP" },
  { num: 5, title: "SQL Agent", desc: "自然语言查询" },
];

export default function WorkflowStepper({ step }: { step: number }) {
  return (
    <nav className="workflow">
      {STEPS.map((s) => (
        <div key={s.num} className={s.num <= step ? "step active" : "step"}>
          <span className="step-num">{s.num}</span>
          <b>{s.title}</b>
          {s.desc}
        </div>
      ))}
    </nav>
  );
}
