import type { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: ReactNode;
  label: string;
  tone?: "primary" | "secondary" | "danger" | "good";
};

export function IconButton({ icon, label, tone = "secondary", className, ...props }: IconButtonProps) {
  return (
    <button className={clsx("icon-button", `button-${tone}`, className)} type="button" title={label} aria-label={label} {...props}>
      {icon}
      <span>{label}</span>
    </button>
  );
}
