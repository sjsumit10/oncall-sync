import { useId } from "react";
import type { InputHTMLAttributes } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export function Field({
  label,
  error,
  className,
  containerClassName,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  containerClassName?: string;
}) {
  const id = useId();
  return (
    <div className={cn("space-y-1.5", containerClassName)}>
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} className={className} {...props} />
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
