export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error || "未知错误");
  return <div className="error-state">{message}</div>;
}
