export type AppNavigationId = "chat" | "campaigns" | "posts" | "metrics" | "memories";

export type AppNavigationItem = {
  id: AppNavigationId;
  label: string;
  href: string;
};

export const APP_NAVIGATION_ITEMS: AppNavigationItem[] = [
  { id: "chat", label: "チャット", href: "/chat" },
  { id: "campaigns", label: "施策", href: "/campaigns" },
  { id: "posts", label: "投稿", href: "/posts" },
  { id: "metrics", label: "計測結果", href: "/metrics" },
  { id: "memories", label: "記憶", href: "/memories" },
];

export function navigationIdFromPath(pathname: string): AppNavigationId {
  const firstSegment = pathname.split("/").filter(Boolean)[0];
  return APP_NAVIGATION_ITEMS.find((navigationItem) => navigationItem.id === firstSegment)?.id ?? "chat";
}
