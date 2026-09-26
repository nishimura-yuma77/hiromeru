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
      description="URLが正しいかご確認ください。ページが移動または削除された可能性があります。"
      actions={
        <Link href="/" style={routeStateActionStyle}>
          ホームへ戻る
        </Link>
      }
    />
  );
}
