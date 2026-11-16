import { AppShell } from "@/components/shell";
import { PlacoProvider } from "@/components/providers";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <PlacoProvider>
      <AppShell>{children}</AppShell>
    </PlacoProvider>
  );
}
