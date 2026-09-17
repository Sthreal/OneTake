const STEPS = [
  { number: 1, title: "素材输入", detail: "图片与商品信息" },
  { number: 2, title: "商品识别", detail: "确认商品主体" },
  { number: 3, title: "主图与文案", detail: "处理并编辑内容" },
  { number: 4, title: "视频与成片", detail: "生成并下载" },
];

interface FlowProgressProps {
  currentStep?: number;
}

export function FlowProgress({ currentStep = 1 }: FlowProgressProps) {
  return (
    <section className="flow-progress" aria-label="商品视频生成进度">
      {STEPS.map((step, index) => {
        const status = step.number < currentStep ? "completed" : step.number === currentStep ? "active" : "locked";
        return (
          <div className={"flow-segment is-" + status} key={step.number}>
            <span className="flow-index">{status === "completed" ? "✓" : step.number}</span>
            <span className="flow-copy">
              <strong>{step.title}</strong>
              <small>{step.detail}</small>
            </span>
            {index < STEPS.length - 1 ? <span className={"flow-connector is-" + status} aria-hidden="true" /> : null}
          </div>
        );
      })}
    </section>
  );
}
