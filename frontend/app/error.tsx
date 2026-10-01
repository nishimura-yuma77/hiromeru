"use client";

import Link from "next/link";

import {
  RouteState,
  routeStateSecondaryActionStyle,
} from "@/app/_components/RouteState";
import { Button } from "@/shared/components/Button/Button";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <RouteState
      eyebrow="ERROR"
      title="問題が発生しました"
      description="ページを表示できませんでした。時間をおいて、もう一度お試しください。"
      live="assertive"
      actions={
        <>
          <Button onClick={reset}>もう一度試す</Button>
          <Link href="/" style={routeStateSecondaryActionStyle}>
            ホームへ戻る
          </Link>
        </>
      }
    />
  );
}
