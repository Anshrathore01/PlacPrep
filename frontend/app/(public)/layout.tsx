import { AppShell } from "@/components/shell";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
