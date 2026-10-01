import { useRef, useState } from "react";
import { uploadFile, SAMPLE_DATA_URL } from "../api";
import type { UploadResponse } from "../types";

interface Props {
  disabled: boolean;
  onUploaded: (d: {
    sessionId: string;
    columns: string[];
    mapping: Record<string, string | null>;
    dimensions: UploadResponse["dimensions"];
    snapshots: string[];
  }) => void;
}

export default function UploadPanel({ disabled, onUploaded }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("尚未上传文件");
  const [busy, setBusy] = useState(false);

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return alert("请选择 Excel 或 CSV 文件");
    setBusy(true);
    setStatus("上传并识别字段中...");
    try {
      const d = await uploadFile(file);
      onUploaded({
        sessionId: d.session_id,
        columns: d.columns,
        mapping: d.mapping,
        dimensions: d.dimensions,
        snapshots: d.snapshots,
      });
      setStatus(
        `已读取 ${d.rows} 行，识别到 ${d.snapshot_count} 个数据快照和 ${d.dimensions.length} 个可用分群维度。请确认字段映射后，点击“生成分析方案”或“按当前方案生成报告”。`
      );
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>上传整理后的查询结果</h2>
          <p className="panel-kicker">支持一次上传全量客户数据，系统会自动读取字段并完成客户级聚合。</p>
        </div>
        <span className="section-tag">DATA INPUT</span>
      </div>
      <div className="upload">
        <div className="upload-copy">
          <div className="upload-title">选择本周数据文件</div>
          <div className="muted">
            建议包含客户代码、行业、权益购买/使用、到期天数、合同金额等字段。没有数据？先下载右侧样例试用。
          </div>
          <span className="upload-status">{status}</span>
        </div>
        <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" disabled={disabled} />
        <a
          className="button button-ghost"
          href={SAMPLE_DATA_URL}
          download
          style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          ⬇ 下载样例数据
        </a>
        <button onClick={handleUpload} disabled={disabled || busy}>
          {disabled ? "已上传" : "上传并识别字段"}
        </button>
      </div>
    </section>
  );
}
