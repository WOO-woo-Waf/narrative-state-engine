import { useState } from "react";
import { Bot, Lock, MessageSquareMore, Pencil, ShieldQuestion, X } from "lucide-react";
import { JsonPreview } from "../../components/data/JsonPreview";
import { IconButton } from "../../components/form/IconButton";
import { StatusPill } from "../../components/data/StatusPill";
import type { CandidateItem, EvidenceLink } from "../../types/state";
import { objectTypeLabel, operationLabel, statusLabel } from "../../utils/labels";

export function CandidateDiffPanel({
  candidate,
  evidence,
  onAccept,
  onReject,
  onLock,
  onRequestEvidence,
  onEditWithModel,
  onEditManually
}: {
  candidate?: CandidateItem;
  evidence: EvidenceLink[];
  onAccept: () => void;
  onReject: () => void;
  onLock: () => void;
  onRequestEvidence: () => void;
  onEditWithModel: () => void;
  onEditManually: (value: string) => void;
}) {
  const [manualOpen, setManualOpen] = useState(false);
  const [manualValue, setManualValue] = useState("");
  if (!candidate) return <div className="empty-state">请选择一个候选查看字段差异。</div>;
  const beforeValue = candidate.before_value ?? "后端未提供修改前内容";
  const afterValue = candidate.proposed_value ?? candidate.proposed_payload ?? null;
  const editableValue = manualValue || formatValue(afterValue);
  return (
    <div className="stack">
      <article className="detail-card">
        <header>
          <div>
            <h3>{candidate.field_path || candidate.target_object_id || candidate.candidate_item_id}</h3>
            <p className="muted">{objectTypeLabel(candidate.target_object_type)} / {operationLabel(candidate.operation || "upsert")}</p>
          </div>
          <StatusPill value={statusLabel(candidate.status || "candidate")} />
        </header>
        <div className="diff-grid">
          <section>
            <h4>修改前</h4>
            <pre>{formatValue(beforeValue)}</pre>
          </section>
          <section>
            <h4>修改后</h4>
            <pre>{formatValue(afterValue)}</pre>
          </section>
        </div>
        {candidate.conflict_reason ? <div className="notice notice-warn">{candidate.conflict_reason}</div> : null}
      </article>
      <div className="button-row wrap">
        <IconButton icon={<ShieldQuestion size={16} />} label="接受字段" tone="good" onClick={onAccept} />
        <IconButton icon={<X size={16} />} label="拒绝字段" tone="danger" onClick={onReject} />
        <IconButton icon={<Bot size={16} />} label="让模型编辑" tone="secondary" onClick={onEditWithModel} />
        <IconButton icon={<Pencil size={16} />} label="手动编辑" tone="secondary" onClick={() => setManualOpen((open) => !open)} />
        <IconButton icon={<Lock size={16} />} label="锁定字段" tone="secondary" onClick={onLock} />
        <IconButton icon={<MessageSquareMore size={16} />} label="请求证据" tone="secondary" onClick={onRequestEvidence} />
      </div>
      {manualOpen ? (
        <section className="manual-editor">
          <label className="field">
            <span>手动填写候选值。这里只创建待审计候选，不会直接写入主状态。</span>
            <textarea value={editableValue} onChange={(event) => setManualValue(event.target.value)} />
          </label>
          <IconButton icon={<Pencil size={16} />} label="提交手动候选" tone="primary" onClick={() => onEditManually(editableValue)} />
        </section>
      ) : null}
      <section>
        <h3 className="subheading">证据摘录</h3>
        {evidence.length ? (
          evidence.slice(0, 8).map((item) => (
            <blockquote className="quote" key={item.evidence_id}>
              {item.quote_text || item.evidence_id}
            </blockquote>
          ))
        ) : (
          <div className="empty-state">暂无关联证据。</div>
        )}
      </section>
      <JsonPreview title="候选原始数据" value={candidate} />
    </div>
  );
}

function formatValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}
