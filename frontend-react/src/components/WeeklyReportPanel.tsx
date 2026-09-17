import { useRef, useState } from "react";

interface Props {
  html: string;
}

const PRINT_CSS =
  "<style>@page{size:A4;margin:14mm}@media print{html,body{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}.plotly,.js-plotly-plot,svg,img,table,section,.card,.panel{page-break-inside:avoid;break-inside:avoid}}body{margin:0}</style>";

export default function WeeklyReportPanel({ html }: Props) {
  const [pdfStatus, setPdfStatus] = useState("");
  const frameRef = useRef<HTMLIFrameElement>(null);

  function buildPrintDoc(docHtml: string) {
    const marker = "</head>";
    return docHtml.includes(marker)
      ? docHtml.replace(marker, PRINT_CSS + marker)
      : PRINT_CSS + docHtml;
  }

  function downloadHtml() {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    a.download = "entitlement_weekly_report.html";
    a.click();
  }

  function exportPdf() {
    if (!html) return setPdfStatus("请先生成周报");
    setPdfStatus("正在准备打印视图...");
    const frame = document.createElement("iframe");
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText =
      "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
    document.body.appendChild(frame);
    let done = false;
    const cleanup = () => {
      done = true;
      setTimeout(() => frame.remove(), 800);
    };
    try {
      const w = frame.contentWindow;
      if (!w) throw new Error("无法创建打印窗口");
      w.onafterprint = cleanup;
      const doc = frame.contentDocument;
      doc?.open();
      doc?.write(buildPrintDoc(html));
      doc?.close();
      setTimeout(() => {
        if (done) return;
        try {
          w.focus();
          w.print();
          setPdfStatus("已打开打印窗口，请在目标中选择“另存为 PDF”");
        } catch (e) {
          setPdfStatus("导出失败：" + (e instanceof Error ? e.message : String(e)));
        }
        cleanup();
      }, 1400);
    } catch (e) {
      setPdfStatus("导出失败：" + (e instanceof Error ? e.message : String(e)));
      frame.remove();
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>正式周报预览</h2>
          <p className="panel-kicker">可直接交付业务团队，一键导出 PDF 或下载 HTML。</p>
        </div>
        <span className="section-tag">DELIVERABLE</span>
      </div>
      <div className="frame-wrap">
        <iframe ref={frameRef} title="weekly-report" srcDoc={html} />
      </div>
      <p style={{ margin: "12px 0 0" }} className="report-actions">
        <button onClick={exportPdf}>导出 PDF</button>
        <button className="button-ghost" onClick={downloadHtml}>下载 HTML 周报</button>
        <span className="agent-status">{pdfStatus}</span>
      </p>
    </section>
  );
}
