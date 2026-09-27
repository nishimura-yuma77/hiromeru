import Link from "next/link";

import {
  RouteState,
  routeStateActionStyle,
} from "@/app/_components/RouteState";

export default function NotFound() {
  return (
    <RouteState
      eyebrow="404"
      title="ページが見つかりません"
      description="お探しのページは移動または削除された可能性があります。"
      actions={
        <Link href="/chat" style={routeStateActionStyle}>
          チャットへ戻る
        </Link>
      }
    />
  );
}
