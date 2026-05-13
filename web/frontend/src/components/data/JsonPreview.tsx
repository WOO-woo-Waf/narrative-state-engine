import { lazy, Suspense, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { LoadingState } from "../feedback/LoadingState";

const Editor = lazy(() => import("@monaco-editor/react"));

export function JsonPreview({ value, title = "JSON", collapsed = true }: { value: unknown; title?: string; collapsed?: boolean }) {
  const [open, setOpen] = useState(!collapsed);
  const json = JSON.stringify(value ?? null, null, 2);
  return (
    <section className="json-preview">
      <button className="section-toggle" type="button" onClick={() => setOpen((item) => !item)}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
      </button>
      {open ? (
        <Suspense fallback={<LoadingState label="正在加载 JSON 编辑器" />}>
          <Editor
            height="280px"
            defaultLanguage="json"
            value={json}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              wordWrap: "on",
              fontSize: 12,
              lineNumbers: "off"
            }}
          />
        </Suspense>
      ) : null}
    </section>
  );
}
