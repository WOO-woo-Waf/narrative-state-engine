export function LoadingState({ label = "加载中" }: { label?: string }) {
  return <div className="empty-state">{label}</div>;
}
