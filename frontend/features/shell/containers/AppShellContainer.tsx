"use client";

import { useEffect, useReducer, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { AppShell } from "@/features/shell/components/AppShell/AppShell";
import {
  APP_NAVIGATION_ITEMS,
  navigationIdFromPath,
} from "@/features/shell/types/navigation";

type AppShellContainerProps = {
  email: string;
  logoutLoading: boolean;
  logoutError: string | null;
  onLogout: () => void;
  children: ReactNode;
};

type DrawerState = { isOpen: boolean };
type DrawerEvent = { type: "opened" } | { type: "closed" };

function drawerReducer(state: DrawerState, event: DrawerEvent): DrawerState {
  switch (event.type) {
    case "opened":
      return { isOpen: true };
    case "closed":
      return { isOpen: false };
  }
}

export function AppShellContainer(props: AppShellContainerProps) {
  const pathname = usePathname();
  const [drawer, dispatch] = useReducer(drawerReducer, { isOpen: false });
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerCloseButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!drawer.isOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    const menuButton = menuButtonRef.current;
    document.body.style.overflow = "hidden";
    drawerCloseButtonRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        dispatch({ type: "closed" });
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) {
        return;
      }

      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      const first = focusable.item(0);
      const last = focusable.item(focusable.length - 1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      menuButton?.focus();
    };
  }, [drawer.isOpen]);

  return (
    <AppShell
      email={props.email}
      navigationItems={APP_NAVIGATION_ITEMS}
      activeNavigationId={navigationIdFromPath(pathname)}
      drawerOpen={drawer.isOpen}
      logoutLoading={props.logoutLoading}
      logoutError={props.logoutError}
      menuButtonRef={menuButtonRef}
      drawerRef={drawerRef}
      drawerCloseButtonRef={drawerCloseButtonRef}
      onDrawerOpen={() => dispatch({ type: "opened" })}
      onDrawerClose={() => dispatch({ type: "closed" })}
      onLogout={props.onLogout}
    >
      {props.children}
    </AppShell>
  );
}
