import { RouteState } from "@/app/_components/RouteState";

export default function Loading() {
  return (
    <RouteState
      eyebrow="LOADING"
      title="読み込み中です"
      description="ページを準備しています。しばらくお待ちください。"
      live="polite"
    />
  );
}
