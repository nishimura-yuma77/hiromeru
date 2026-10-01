"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { Button } from "@/shared/components/Button/Button";
import { Input } from "@/shared/components/Input/Input";
import { Spinner } from "@/shared/components/Spinner/Spinner";

import styles from "./SearchCombobox.module.scss";

export function SearchCombobox<T extends { id: number; title: string }>({
  id,
  label,
  value,
  onValueChange,
  options,
  onSelect,
  open,
  onOpenChange,
  loading = false,
  searchError = "",
  fieldError = "",
  disabled = false,
  type = "text",
  placeholder,
  hideLabel = false,
  emptyMessage = "該当する施策がありません",
  loadingMessage = "施策を検索中…",
  renderOption,
}: {
  id: string;
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: T[];
  onSelect: (option: T) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loading?: boolean;
  searchError?: string;
  fieldError?: string;
  disabled?: boolean;
  type?: "text" | "search";
  placeholder?: string;
  hideLabel?: boolean;
  emptyMessage?: string;
  loadingMessage?: string;
  renderOption?: (option: T) => ReactNode;
}) {
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = `${id}-options`;
  const visible = open && !disabled;

  useEffect(() => {
    function onOutsideClick(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) onOpenChange(false);
    }
    document.addEventListener("pointerdown", onOutsideClick);
    return () => document.removeEventListener("pointerdown", onOutsideClick);
  }, [onOpenChange]);

  function choose(option: T) {
    inputRef.current?.focus();
    onSelect(option);
    onOpenChange(false);
    setActiveIndex(-1);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { onOpenChange(false); setActiveIndex(-1); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      onOpenChange(true);
      if (!options.length || loading) return;
      setActiveIndex((current) => event.key === "ArrowDown"
        ? (current + 1) % options.length
        : (current <= 0 ? options.length - 1 : current - 1));
    }
    if (event.key === "Enter" && visible && !loading && activeIndex >= 0 && options[activeIndex]) {
      event.preventDefault();
      choose(options[activeIndex]);
    }
  }

  return (
    <div className={styles.root} ref={rootRef} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) onOpenChange(false);
    }}>
      <label className={hideLabel ? styles.visuallyHidden : styles.label} htmlFor={id}>{label}</label>
      <Input ref={inputRef} id={id} type={type} value={value} disabled={disabled} placeholder={placeholder} autoComplete="off"
        role="combobox" aria-autocomplete="list" aria-controls={listId} aria-expanded={visible}
        aria-activedescendant={visible && !loading && activeIndex >= 0 && options[activeIndex] ? `${listId}-${options[activeIndex].id}` : undefined}
        aria-describedby={fieldError ? `${id}-error` : `${id}-status`}
        aria-invalid={Boolean(fieldError)}
        onFocus={() => { if (!disabled) onOpenChange(true); }}
        onChange={(event) => { setActiveIndex(-1); onValueChange(event.currentTarget.value); onOpenChange(true); }}
        onKeyDown={onKeyDown}
      />
      <div id={listId} className={styles.panel} role="listbox" aria-label="施策の候補" aria-hidden={!visible} inert={!visible}>
        {loading ? <p className={styles.message}><Spinner size="small" />{loadingMessage}</p>
          : searchError ? <p className={styles.message}>{searchError}</p>
          : options.length ? options.map((option, index) => (
            <Button variant="ghost" size="small" role="option" tabIndex={-1} aria-selected={index === activeIndex}
              id={`${listId}-${option.id}`} key={option.id} onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(option)}>{renderOption ? renderOption(option) : option.title}</Button>
          )) : <p className={styles.message}>{emptyMessage}</p>}
      </div>
      <p id={`${id}-status`} className={styles.status} aria-live="polite">
        {visible ? loading ? loadingMessage : searchError || `${options.length}件の候補があります` : ""}
      </p>
      {fieldError ? <p id={`${id}-error`} className={styles.error} role="alert">{fieldError}</p> : null}
    </div>
  );
}
