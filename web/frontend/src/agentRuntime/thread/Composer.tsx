import { RotateCcw, Send, Square } from "lucide-react";
import { useState } from "react";

export function Composer({
  disabled,
  isSending,
  attachmentSummary,
  prompts,
  onSend,
  onRetry,
  onStop
}: {
  disabled?: boolean;
  isSending?: boolean;
  attachmentSummary?: string;
  prompts: string[];
  onSend: (message: string) => void;
  onRetry?: () => void;
  onStop?: () => void;
}) {
  const [text, setText] = useState("");
  function submit(value = text) {
    const next = value.trim();
    if (!next || disabled || isSending) return;
    onSend(next);
    setText("");
  }
  return (
    <footer className="agent-composer">
      {attachmentSummary ? <div className="agent-composer-attachment">{attachmentSummary}</div> : null}
      <div className="agent-prompt-row">
        {prompts.map((prompt) => (
          <button type="button" key={prompt} onClick={() => submit(prompt)} disabled={disabled || isSending}>
            {prompt}
          </button>
        ))}
      </div>
      <div className="agent-composer-box">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="向 Agent 说明你的下一步意图..."
          rows={3}
          disabled={disabled}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit();
          }}
        />
        <div className="agent-composer-actions">
          <button type="button" onClick={onRetry} disabled={!onRetry || isSending} title="重试">
            <RotateCcw size={17} />
          </button>
          <button type="button" onClick={onStop} disabled={!isSending || !onStop} title="停止">
            <Square size={17} />
          </button>
          <button type="button" onClick={() => submit()} disabled={disabled || isSending || !text.trim()} title="发送">
            <Send size={17} />
            发送
          </button>
        </div>
      </div>
    </footer>
  );
}
