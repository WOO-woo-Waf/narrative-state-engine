import { JsonPreview } from "../../components/data/JsonPreview";
import { StatusPill } from "../../components/data/StatusPill";
import type { StateObject } from "../../types/state";
import { authorityLabel } from "../../utils/labels";

export function StateObjectInspector({ objects }: { objects: StateObject[] }) {
  if (!objects.length) return <div className="empty-state">请从图谱节点或状态对象列表中选择一个对象。</div>;
  return (
    <div className="stack">
      {objects.map((object) => (
        <article className="detail-card" key={object.object_id}>
          <header>
            <h3>{object.display_name || object.object_key || object.object_id}</h3>
            <StatusPill value={authorityLabel(object.authority)} />
          </header>
          <div className="key-value-list">
            <div>
              <span>类型</span>
              <strong>{object.object_type || "未知"}</strong>
            </div>
            <div>
              <span>置信度</span>
              <strong>{Math.round(Number(object.confidence || 0) * 100)}%</strong>
            </div>
            <div>
              <span>锁定</span>
              <StatusPill value={object.author_locked ? "作者锁定" : "未锁定"} tone={object.author_locked ? "good" : "info"} />
            </div>
          </div>
          <JsonPreview title="对象原始数据" value={object.payload || object} />
        </article>
      ))}
    </div>
  );
}
