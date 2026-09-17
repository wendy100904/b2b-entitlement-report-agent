const REQUIRED_FIELDS = [
  "customer_id", "data_date", "industry", "company_size", "renewal_type",
  "active_type", "ownership", "city_tier", "package_products", "used_products",
  "use_times", "type_cnt", "use_period", "max_success_day", "renewal_days",
  "annual_value",
];

interface Props {
  columns: string[];
  mapping: Record<string, string | null>;
  onChange: (mapping: Record<string, string | null>) => void;
}

export default function MappingPanel({ columns, mapping, onChange }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>确认字段映射</h2>
          <p className="panel-kicker">自动识别结果可手动调整，缺失字段会在报告中标注为不可用。</p>
        </div>
        <span className="section-tag">SCHEMA</span>
      </div>
      <div className="maps">
        {REQUIRED_FIELDS.map((key) => (
          <label key={key}>
            {key}
            <select
              value={mapping[key] ?? ""}
              onChange={(e) => onChange({ ...mapping, [key]: e.target.value || null })}
            >
              <option value="">不映射</option>
              {columns.map((c) => (
                <option key={c} value={c} selected={mapping[key] === c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </section>
  );
}
