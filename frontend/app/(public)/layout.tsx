import { AppShell } from "@/components/shell";
import { AppProviders } from "@/components/providers";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <AppProviders><AppShell>{children}</AppShell></AppProviders>;
}
