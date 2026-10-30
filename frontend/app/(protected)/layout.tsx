import { AppShell } from "@/components/shell";
import { AppProviders, Protected } from "@/components/providers";

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppProviders>
      <Protected>
        <AppShell>{children}</AppShell>
      </Protected>
    </AppProviders>
  );
}
