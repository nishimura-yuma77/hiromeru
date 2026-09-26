"use client";

import Link from "next/link";

import {
  RouteState,
  routeStateActionStyle,
  routeStateSecondaryActionStyle,
} from "@/app/_components/RouteState";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <RouteState
      eyebrow="ERROR"
      title="問題が発生しました"
      description="ページを表示できませんでした。時間をおいて、もう一度お試しください。"
      live="assertive"
      actions={
        <>
          <button type="button" onClick={reset} style={routeStateActionStyle}>
            もう一度試す
          </button>
          <Link href="/" style={routeStateSecondaryActionStyle}>
            ホームへ戻る
          </Link>
        </>
      }
    />
  );
}
